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
"""Represents an Azure account."""
import base64
from time import sleep
from typing import Optional, Dict, List, Tuple, Any

# Pylint complains about the import but the library imports just fine,
# so we can ignore the warning.
# pylint: disable=import-error
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.v2016_04_30_preview.models import DiskCreateOption
from msrestazure.azure_exceptions import CloudError
from sshpubkeys import SSHKey, InvalidKeyError
# pylint: enable=import-error

from libcloudforensics.providers.azure.internal import compute, common
from libcloudforensics.scripts import utils


class AZAccount:
  """Class that represents an Azure Account.

  Attributes:
    subscription_id (str): The Azure subscription ID to use.
    credentials (ServicePrincipalCredentials): An Azure credentials object.
    compute_client (ComputeManagementClient): An Azure compute client object.
  """

  def __init__(self,
               subscription_id: str,
               default_resource_group_name: str,
               default_region: Optional[str] = None) -> None:
    """Initialize the AZAccount class.

    Args:
      subscription_id (str): The Azure subscription ID to use.
      default_resource_group_name (str): The default resource group in which to
          create new resources in.
      default_region (str): Optional. The default region to create new
          resources in. Default is eastus.
    """
    self.subscription_id = subscription_id
    self.default_resource_group_name = default_resource_group_name
    self.default_region = default_region or 'eastus'
    self.credentials = common.GetCredentials()
    self.compute_client = ComputeManagementClient(
        self.credentials, self.subscription_id)
    self.network_client = NetworkManagementClient(
        self.credentials, self.subscription_id
    )

  def ListInstances(self,
                    resource_group_name: Optional[str] = None
                    ) -> Dict[str, compute.AZVirtualMachine]:
    """List instances in an Azure subscription / resource group.

    Args:
      resource_group_name (str): Optional. The resource group name to list
          instances from. If none specified, then all instances in the Azure
          subscription will be listed.

    Returns:
      Dict[str, AZVirtualMachine]: Dictionary mapping instance names (str) to
          their respective AZVirtualMachine object.
    """
    instances = {}  # type: Dict[str, compute.AZVirtualMachine]
    az_vm_client = self.compute_client.virtual_machines
    if not resource_group_name:
      responses = common.ExecuteRequest(az_vm_client, 'list_all')
    else:
      responses = common.ExecuteRequest(
          az_vm_client,
          'list',
          {'resource_group_name': resource_group_name})
    for response in responses:
      for instance in response:
        instances[instance.name] = compute.AZVirtualMachine(
            self,
            instance.id,
            instance.name,
            instance.location,
            zones=instance.zones)
    return instances

  def ListDisks(
      self,
      resource_group_name: Optional[str] = None) -> Dict[str, compute.AZDisk]:
    """List disks in an Azure subscription / resource group.

    Args:
      resource_group_name (str): Optional. The resource group name to list
          disks from. If none specified, then all disks in the AZ
          subscription will be listed.

    Returns:
      Dict[str, AZDisk]: Dictionary mapping disk names (str) to their
          respective AZDisk object.
    """
    disks = {}  # type: Dict[str, compute.AZDisk]
    az_disk_client = self.compute_client.disks
    if not resource_group_name:
      responses = common.ExecuteRequest(az_disk_client, 'list')
    else:
      responses = common.ExecuteRequest(
          az_disk_client,
          'list_by_resource_group',
          {'resource_group_name': resource_group_name})
    for response in responses:
      for disk in response:
        disks[disk.name] = compute.AZDisk(self,
                                          disk.id,
                                          disk.name,
                                          disk.location,
                                          zones=disk.zones)
    return disks

  def GetInstance(
      self,
      instance_name: str,
      resource_group_name: Optional[str] = None) -> compute.AZVirtualMachine:
    """Get instance from AZ subscription / resource group.

    Args:
      instance_name (str): The instance name.
      resource_group_name (str): Optional. The resource group name to look
          the instance in. If none specified, then the instance will be fetched
          from the AZ subscription.

    Returns:
      AZVirtualMachine: An Azure virtual machine object.

    Raises:
      RuntimeError: If the instance was not found in the subscription / resource
          group.
    """
    instances = self.ListInstances(resource_group_name=resource_group_name)
    if instance_name not in instances:
      error_msg = 'Instance {0:s} was not found in subscription {1:s}'.format(
          instance_name, self.subscription_id)
      raise RuntimeError(error_msg)
    return instances[instance_name]

  def GetDisk(
      self,
      disk_name: str,
      resource_group_name: Optional[str] = None) -> compute.AZDisk:
    """Get disk from AZ subscription / resource group.

    Args:
      disk_name (str): The disk name.
      resource_group_name (str): Optional. The resource group name to look
          the disk in. If none specified, then the disk will be fetched from
          the AZ subscription.

    Returns:
      AZDisk: An Azure Compute Disk object.

    Raises:
      RuntimeError: If the disk was not found in the subscription / resource
          group.
    """
    disks = self.ListDisks(resource_group_name=resource_group_name)
    if disk_name not in disks:
      error_msg = 'Disk {0:s} was not found in subscription {1:s}'.format(
          disk_name, self.subscription_id)
      raise RuntimeError(error_msg)
    return disks[disk_name]

  def CreateDiskFromSnapshot(
      self,
      snapshot: compute.AZSnapshot,
      disk_name: Optional[str] = None,
      disk_name_prefix: Optional[str] = None,
      disk_type: str = 'Standard_LRS') -> compute.AZDisk:
    """Create a new disk based on a Snapshot.

    Args:
      snapshot (AZSnapshot): Snapshot to use.
      disk_name (str): Optional. String to use as new disk name.
      disk_name_prefix (str): Optional. String to prefix the disk name with.
      disk_type (str): Optional. The sku name for the disk to create. Can be
          Standard_LRS, Premium_LRS, StandardSSD_LRS, or UltraSSD_LRS. The
          default value is Standard_LRS.

    Returns:
      AZDisk: Azure Compute Disk.

    Raises:
      RuntimeError: If the disk could not be created.
    """

    if not disk_name:
      disk_name = common.GenerateDiskName(snapshot,
                                          disk_name_prefix=disk_name_prefix)
    creation_data = {
        'location': snapshot.region,
        'creation_data': {
            'sourceResourceId': snapshot.resource_id,
            'create_option': DiskCreateOption.copy
        }
    }

    try:
      request = self.compute_client.disks.create_or_update(
          snapshot.resource_group_name,
          disk_name,
          creation_data,
          sku=disk_type)
      while not request.done():
        sleep(5)  # Wait 5 seconds before checking disk status again
      disk = request.result()
    except CloudError as exception:
      raise RuntimeError('Could not create disk from snapshot {0:s}: {1:s}'
                         .format(snapshot.resource_id, str(exception)))

    return compute.AZDisk(self,
                          disk.id,
                          disk.name,
                          disk.location,
                          disk.zones)

  def GetOrCreateAnalysisVm(
      self,
      vm_name: str,
      boot_disk_size: int,
      cpu_cores: int,
      memory_in_mb: int,
      ssh_public_key: str,
      packages: Optional[List[str]] = None,
      tags: Optional[Dict[str, str]] = None) -> Tuple[compute.AZVirtualMachine, bool]:  # pylint: disable=line-too-long
    """Get or create a new virtual machine for analysis purposes.

        Args:
          vm_name (str): The instance name tag of the virtual machine.
          boot_disk_size (int): The size of the analysis VM boot volume (in GB).
          cpu_cores (int): Number of CPU cores for the analysis VM.
          memory_in_mb (int): The memory size (in MB) for the analysis VM.
          ssh_public_key (str): A SSH public key data to associate with the
              VM. This must be provided as otherwise the VM will not be
              accessible.
          packages (List[str]): Optional. List of packages to install in the VM.
          tags (Dict[str, str]): Optional. A dictionary of tags to add to the
              instance, for example {'TicketID': 'xxx'}. An entry for the
              instance name is added by default.

        Returns:
          Tuple[AWSInstance, bool]: A tuple with an AZVirtualMachine object
              and a boolean indicating if the virtual machine was created
              (True) or reused (False).

        Raises:
          RuntimeError: If the virtual machine cannot be found or created.
        """

    # Re-use instance if it already exists, or create a new one.
    try:
      instance = self.GetInstance(vm_name)
      if instance:
        created = False
        return instance, created
    except RuntimeError:
      pass

    # Validate SSH public key format
    try:
      SSHKey(ssh_public_key, strict=True).parse()
    except InvalidKeyError as exception:
      raise RuntimeError('The provided public SSH key is invalid: '
                         '{0:s}'.format(str(exception)))

    instance_type = self._GetInstanceType(cpu_cores, memory_in_mb)
    startup_script = utils.ReadStartupScript()
    if packages:
      startup_script = startup_script.replace('${packages[@]}', ' '.join(
          packages))

    creation_data = {
        'location': self.default_region,
        'properties': {
            'hardwareProfile': {'vmSize': instance_type},
            'storageProfile': {
                'imageReference': {
                    'sku': '18.04-LTS',
                    'publisher': 'Canonical',
                    'version': 'latest',
                    'offer': 'UbuntuServer'}
            },
            'osDisk': {
                'caching': "ReadWrite",
                'managedDisk': {'storageAccountType': 'Standard_LRS'},
                'name': 'os-disk-{0:s}'.format(vm_name),
                'diskSizeGb': boot_disk_size,
                'createOption': 'FromImage'
            },
            'osProfile': {
                'adminUsername': 'AzureUser',
                'computerName': vm_name,
                # Azure requires the startup script to be sent as a b64 string
                'customData': base64.b64encode(
                    str.encode(startup_script)).decode('utf-8'),
                'linuxConfiguration': {
                    'ssh': {
                        'publicKeys': [{
                            'path': '/home/AzureUser/.ssh/authorized_keys',
                            'keyData': ssh_public_key}]
                    }
                }
            },
            'networkProfile': {
                'networkInterfaces': [{'id': self._CreateNetworkInterfaceForVM(
                    vm_name, self.default_region)}]
            }
        }
    }  # type: Dict[str, Any]

    if tags:
      creation_data['tags'] = tags

    try:
      request = self.compute_client.virtual_machines.create_or_update(
          self.default_resource_group_name,
          vm_name,
          creation_data
      )
      while not request.done():
        sleep(5)  # Wait 5 seconds before checking disk status again
      vm = request.result()
    except CloudError as exception:
      raise RuntimeError('Could not create instance {0:s}: {1:s}'.format(
          vm_name, str(exception)))

    instance = compute.AZVirtualMachine(self,
                                        vm.id,
                                        vm.name,
                                        vm.location,
                                        zones=vm.zones)
    created = True
    return instance, created

  def ListInstanceTypes(self,
                        region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns a list of available VM sizes for a given region.

    Args:
      region (str): Optional. The region in which to look the instance types.
          By default, look in the default_region associated to the AZAccount
          object.

    Returns:
      List[Dict[str, str]]: A list of available vm size. Each size is a
          dictionary containing the name of the configuration, the number of
          CPU cores, and the amount of available memory (in MB).
          E.g.: {'Name': 'Standard_B1ls', 'CPU': 1, 'Memory': 512}
    """
    if not region:
      region = self.default_region
    available_vms = self.compute_client.virtual_machine_sizes.list(region)
    vm_sizes = []
    for vm in available_vms:
      vm_sizes.append({
          'Name': vm.name,
          'CPU': vm.number_of_cores,
          'Memory': vm.memory_in_mb
      })
    return vm_sizes

  def _GetInstanceType(self, cpu_cores: int, memory_in_mb: int) -> str:
    """Returns an instance type for the given number of CPU cores / memory.

    Args:
      cpu_cores (int): The number of CPU cores.
      memory_in_mb (int): The amount of memory (in MB).

    Returns:
      str: The instance type for the given configuration.

    Raises:
      ValueError: If no instance type matches the requested configuration.
    """
    vm_sizes = self.ListInstanceTypes()
    for size in vm_sizes:
      if size['CPU'] == cpu_cores and size['Memory'] == memory_in_mb:
        instance_type = size['Name']  # type: str
        return instance_type
    raise ValueError(
        'No instance type found for the requested configuration: {0:d} CPU '
        'cores, {1:d} MB memory.'.format(cpu_cores, memory_in_mb))

  def _CreateNetworkInterfaceForVM(self,
                                   vm_name: str,
                                   region: Optional[str] = None) -> str:
    """Create a network interface and returns its ID.

    This is quite cumbersome and in-elegant but it seems like it is necessary
    to create VMs from the SDK.
    See https://docs.microsoft.com/en-us/azure/virtual-machines/windows/python

    Args:
      vm_name (str): The name of the VM to create the network interface for.
      region (str): Optional. The region in which to create the network
          interface. Default uses default_region of the AZAccount object.

    Returns:
      str: The id of the created network interface.

    Raises:
      ValueError: if vm_name is not provided.
      RuntimeError: If no network interface could be created.
    """
    if not vm_name:
      raise ValueError('vm_name cannot be None.')

    if not region:
      region = self.default_region

    try:
      request_ip = self.network_client.public_ip_addresses.create_or_update(
          self.default_resource_group_name,
          '{0:s}-public-ip'.format(vm_name),
          {'location': region, 'public_ip_allocation_method': 'Dynamic'}
      )
      public_ip = request_ip.result()
      request_vnet = self.network_client.virtual_networks.create_or_update(
          self.default_resource_group_name,
          '{0:s}-vnet'.format(vm_name),
          {'location': region,
           'address_space': {'address_prefixes': ['10.0.0.0/16']}}
      )
      vnet = request_vnet.result()
      request_subnet = self.network_client.subnets.create_or_update(
          self.default_resource_group_name,
          vnet.name,
          '{0:s}-subnet'.format(vm_name),
          {'address_prefix': '10.0.0.0/24'}
      )
      subnet = request_subnet.result()
      request_nic = self.network_client.network_interfaces.create_or_update(
          self.default_resource_group_name,
          '{0:s}-nic'.format(vm_name),
          {'location': region,
           'ip_configurations': [{
               'name': '{0:s}-ipconfig'.format(vm_name),
               'public_ip_address': public_ip,
               'subnet': {'id': subnet.id}
           }]}
      )
      nic = request_nic.result()
    except CloudError as exception:
      raise RuntimeError('Could not create network interface: {0:s}'.format(
          str(exception)
      ))
    network_interface_id = nic.id  # type: str
    return network_interface_id
