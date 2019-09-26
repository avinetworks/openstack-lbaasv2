******************
Avi LBaaSv2 Driver
******************

Repository of Avi's Driver for OpenStack LBaaSv2.

Download latest driver package from `releases <https://github.com/avinetworks/openstack-lbaasv2/releases>`_


Avi LBaaSv2 Driver version compatibility Matrix
***********************************************

+---------------------+-------------------------+
| Avi Driver Version  | Avi Controller Version  |
+=====================+=========================+
| 18.2.2              | 18.2.2 onwards          |
+---------------------+-------------------------+
| 18.1.3              | 18.1.3 - 18.2.1         |
+---------------------+-------------------------+


Installation:
*************
Installation instructions and documentation available at
https://avinetworks.com/docs/latest/lbaas-v2-driver


Upgrading the Driver:
*********************
Run following command on OpenStack Controller node hosting the
neutron-server service.

#. Download the required pip/deb/rpm package file from `releases`_ page.
#. Run the package upgrade command on the OpenStack Controller host.
   e.g. pip install --upgrade avi-lbaasv2-18.2.2.tar.gz
#. Restart the neutron-server service.
   e.g. service neutron-server restart

.. _releases: https://github.com/avinetworks/openstack-lbaasv2/releases


Known Issues:
*************
- `Not able to delete OpenStack network after LBaaSv2 resources are deleted`_

.. _Not able to delete OpenStack network after LBaaSv2 resources are deleted: docs/Cleaning-Up-LBaaSv2-Resources.rst
