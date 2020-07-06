# -*- coding: utf-8 -*-
# Copyright 2020 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""End to end test for the Azure module."""

import typing
import unittest
from time import sleep

from msrestazure.azure_exceptions import CloudError  # pylint: disable=import-error

from libcloudforensics.providers.azure.internal.common import LOGGER
from libcloudforensics.providers.azure.internal import account
from libcloudforensics.providers.azure import forensics
from tests.scripts import utils


class EndToEndTest(unittest.TestCase):
  """End to end test on Azure.

  To run these tests, add your project information to a project_info.json file:

  {
    "subscription_id": xxx,  # required
    "resource_group_name": xxx,  # required
    "instance_name": xxx,  # required
    "ssh_public_key": ssh-rsa xxx,  # required
    "disk_name": xxx,  # optional
  }


  Export a PROJECT_INFO environment variable with the absolute path to your
  file: "user@terminal:~$ export PROJECT_INFO='absolute/path/project_info.json'"

  # pylint: disable=line-too-long
  You will also need to configure your AZ account credentials as per the
  guidelines in https://docs.microsoft.com/en-us/azure/developer/python/azure-sdk-authenticate?tabs=cmd
  # pylint: enable=line-too-long
  """

  @classmethod
  @typing.no_type_check
  def setUpClass(cls):
    try:
      project_info = utils.ReadProjectInfo(
          ['subscription_id', 'resource_group_name', 'instance_name',
           'ssh_public_key'])
    except (OSError, RuntimeError, ValueError) as exception:
      raise unittest.SkipTest(str(exception))
    cls.subscription_id = project_info['subscription_id']
    cls.resource_group_name = project_info['resource_group_name']
    cls.instance_to_analyse = project_info['instance_name']
    cls.ssh_public_key = project_info['ssh_public_key']
    cls.disk_to_copy = project_info.get('disk_name', None)
    cls.az = account.AZAccount(cls.subscription_id, cls.resource_group_name)
    cls.analysis_vm_name = 'new-vm-for-analysis'
    cls.analysis_vm, _ = forensics.StartAnalysisVm(cls.subscription_id,
                                                   cls.resource_group_name,
                                                   cls.analysis_vm_name,
                                                   50,
                                                   cls.ssh_public_key)
    cls.disks = []  # List of AZDisks for test cleanup

  @typing.no_type_check
  def testBootDiskCopy(self):
    """End to end test on Azure.

    Test copying the boot disk of an instance.
    """

    disk_copy = forensics.CreateDiskCopy(
        self.subscription_id,
        self.resource_group_name,
        instance_name=self.instance_to_analyse
        # disk_name=None by default, boot disk of instance will be copied
    )
    # The disk should be present in Azure
    remote_disk = self.az.compute_client.disks.get(
        disk_copy.resource_group_name, disk_copy.name)
    self.assertIsNotNone(remote_disk)
    self.assertEqual(disk_copy.name, remote_disk.name)
    self._StoreDiskForCleanup(disk_copy)

  @typing.no_type_check
  def testDiskCopy(self):
    """End to end test on Azure.

    Test copying a specific disk.
    """

    if not self.disk_to_copy:
      return

    disk_copy = forensics.CreateDiskCopy(
        self.subscription_id,
        self.resource_group_name,
        disk_name=self.disk_to_copy)
    # The disk should be present in Azure
    remote_disk = self.az.compute_client.disks.get(
        disk_copy.resource_group_name, disk_copy.name)
    self.assertIsNotNone(remote_disk)
    self.assertEqual(disk_copy.name, remote_disk.name)
    self._StoreDiskForCleanup(disk_copy)

  @typing.no_type_check
  def testStartVm(self):
    """End to end test on Azure.

    Test creating an analysis VM and attaching a copied disk to it.
    """

    disk_copy = forensics.CreateDiskCopy(
        self.subscription_id,
        self.resource_group_name,
        disk_name=self.disk_to_copy)
    self._StoreDiskForCleanup(disk_copy)

    # Create and start the analysis VM and attach the disk
    self.analysis_vm, _ = forensics.StartAnalysisVm(
        self.subscription_id,
        self.resource_group_name,
        self.analysis_vm_name,
        50,
        self.ssh_public_key,
        attach_disks=[disk_copy.name]
    )

    # The forensic instance should be live in the analysis Azure account and
    # the disk should be attached
    instance = self.az.compute_client.virtual_machines.get(
        self.resource_group_name, self.analysis_vm.name
    )
    self.assertEqual(instance.name, self.analysis_vm.name)
    self.assertIn(disk_copy.name, self.analysis_vm.ListDisks())
    self._StoreDiskForCleanup(self.analysis_vm.GetBootDisk())

  @typing.no_type_check
  def _StoreDiskForCleanup(self, disk):
    """Store a disk for cleanup when tests finish.

    Args:
      disk (AZDisk): An Azure disk.
    """
    self.disks.append(disk)

  @classmethod
  @typing.no_type_check
  def tearDownClass(cls):
    # Delete the instance
    LOGGER.info('Deleting instance: {0:s}.'.format(cls.analysis_vm.name))
    request = cls.az.compute_client.virtual_machines.delete(
        cls.analysis_vm.resource_group_name, cls.analysis_vm.name
    )
    while not request.done():
      sleep(5)  # Wait 5 seconds before checking vm deletion status again
    LOGGER.info('Instance {0:s} successfully deleted.'.format(
        cls.analysis_vm.name))
    # Delete the network interface and associated artifacts created for the
    # analysis VM
    LOGGER.info('Deleting network artifacts...')
    cls.az.network_client.network_interfaces.delete(
        cls.resource_group_name, '{0:s}-nic'.format(cls.analysis_vm_name))
    cls.az.network_client.subnets.delete(
        cls.resource_group_name,
        '{0:s}-vnet'.format(cls.analysis_vm_name),
        '{0:s}-subnet'.format(cls.analysis_vm_name))
    cls.az.network_client.virtual_networks.delete(
        cls.resource_group_name, '{0:s}-vnet'.format(cls.analysis_vm_name))
    cls.az.network_client.public_ip_addresses.delete(
        cls.resource_group_name, '{0:s}-public-ip'.format(
            cls.analysis_vm_name))
    # Delete the disks
    for disk in cls.disks:
      LOGGER.info('Deleting disk: {0:s}.'.format(disk.name))
      try:
        cls.az.compute_client.disks.delete(disk.resource_group_name, disk.name)
      except CloudError as exception:
        raise RuntimeError('Could not complete cleanup: {0:s}'.format(
            str(exception)))
      LOGGER.info('Disk {0:s} successfully deleted.'.format(disk.name))


if __name__ == '__main__':
  unittest.main()
