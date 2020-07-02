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
"""Forensics on Azure."""

from typing import TYPE_CHECKING, Optional, List, Dict, Tuple

from libcloudforensics.providers.azure.internal import account, common

if TYPE_CHECKING:
  from libcloudforensics.providers.azure.internal import compute


def CreateDiskCopy(
    subscription_id: str,
    resource_group_name: str,
    instance_name: Optional[str] = None,
    disk_name: Optional[str] = None,
    disk_type: str = 'Standard_LRS') -> 'compute.AZDisk':
  """Creates a copy of an Azure Compute Disk.

  Args:
    subscription_id (str): The Azure subscription ID to use.
    resource_group_name (str): The resource group in which to create the disk
        copy.
    instance_name (str): Optional. Instance name of the instance using the
        disk to be copied. If specified, the boot disk of the instance will be
        copied. If disk_name is also specified, then the disk pointed to by
        disk_name will be copied.
    disk_name (str): Optional. Name of the disk to copy. If not set,
        then instance_name needs to be set and the boot disk will be copied.
    disk_type (str): Optional. The sku name for the disk to create. Can be
          Standard_LRS, Premium_LRS, StandardSSD_LRS, or UltraSSD_LRS. The
          default value is Standard_LRS.

  Returns:
    AZDisk: An Azure Compute Disk object.

  Raises:
    RuntimeError: If there are errors copying the disk.
    ValueError: If both instance_name and disk_name are missing.
  """

  if not instance_name and not disk_name:
    raise ValueError(
        'You must specify at least one of [instance_name, disk_name].')

  az_account = account.AZAccount(subscription_id, resource_group_name)

  try:
    if disk_name:
      disk_to_copy = az_account.GetDisk(disk_name)
    elif instance_name:
      instance = az_account.GetInstance(instance_name)
      disk_to_copy = instance.GetBootDisk()
    common.LOGGER.info('Disk copy of {0:s} started...'.format(
        disk_to_copy.name))
    snapshot = disk_to_copy.Snapshot()
    new_disk = az_account.CreateDiskFromSnapshot(
        snapshot,
        disk_name_prefix=common.DEFAULT_DISK_COPY_PREFIX,
        disk_type=disk_type)
    snapshot.Delete()
    common.LOGGER.info(
        'Disk {0:s} successfully copied to {1:s}'.format(
            disk_to_copy.name, new_disk.name))
  except RuntimeError as exception:
    error_msg = 'Cannot copy disk "{0:s}": {1!s}'.format(
        str(disk_name), str(exception))
    raise RuntimeError(error_msg)

  return new_disk


def StartAnalysisVm(
    subscription_id: str,
    resource_group_name: str,
    vm_name: str,
    boot_disk_size: int,
    cpu_cores: int = 4,
    memory_in_mb: int = 8192,
    attach_disks: Optional[List[str]] = None,
    ssh_public_key: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None) -> Tuple['compute.AZVirtualMachine', bool]:  # pylint: disable=line-too-long
  """Start a virtual machine for analysis purposes.

  Look for an existing Azure virtual machine with name vm_name. If found,
  this instance will be started and used as analysis VM. If not found, then a
  new vm with that name will be created, started and returned. Note that if a
  new vm is created, you should provide the ssh_public_key parameter.

  Args:
    subscription_id (str): The Azure subscription ID to use.
    resource_group_name (str): The resource group in which to create the
        analysis vm.
    vm_name (str): The name for the virtual machine.
    boot_disk_size (int): The size of the analysis VM boot disk (in GB).
    cpu_cores (int): Number of CPU cores for the analysis VM.
    memory_in_mb (int): The memory size (in MB) for the analysis VM.
    attach_disks (List[str]): Optional. List of disk names to attach to the VM.
    ssh_public_key (str): Optional. A SSH public key data to associate
        with the VM. If none provided, then a newly created VM will not
        be accessible.
    tags (Dict[str, str]): Optional. A dictionary of tags to add to the
        instance, for example {'TicketID': 'xxx'}. An entry for the instance
        name is added by default.

  Returns:
    Tuple[AZVirtualMachine, bool]: a tuple with a virtual machine object
        and a boolean indicating if the virtual machine was created or not.
  """

  az_account = account.AZAccount(subscription_id, resource_group_name)

  analysis_vm, created = az_account.GetOrCreateAnalysisVm(
      vm_name,
      boot_disk_size,
      cpu_cores,
      memory_in_mb,
      ssh_public_key=ssh_public_key,
      tags=tags)

  for disk_name in (attach_disks or []):
    analysis_vm.AttachDisk(az_account.GetDisk(disk_name))
  return analysis_vm, created
