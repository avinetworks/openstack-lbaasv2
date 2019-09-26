#############################################################
Cleaning up OpenStack Resources when using Avi LBaaSv2 driver
#############################################################


Issue
=====
Upon deleting LBaaSv2 resources realized using Avi LBaaSv2 driver, Avi
Controller leaves some of the network ports in OpenStack network for
some time and does not delete them immediately. This causes a failure in
deleting the OpenStack network immediately after deleting the LBaaSv2
resources.


Root Cause
==========
Avi Controller uses garbage collection mechanism to delete the network
ports from OpenStack environment. Garbage collection is an independent
background process, and Avi object delete APIs don’t wait for GC to
kick-in or finish. When Virtual Services and pools are deleted from Avi,
the GC usually immediately kicks-in and checks for any network ports to
be deleted and issues port delete request.

The port delete request has two parts: 

#. Detaching the port from Service Engine VM.
#. Once successfully detached, deleting the port.


Once the ports are deleted from OpenStack, the network resource can be deleted.

This entire process of garbage collection can get delayed for following
reasons:

#. In provider-mode, the GC gets delayed when there are other
   operations happening on the SE VM. For example, there is a VS
   being placed on the SE VM from another tenant, and there is
   already a network port attach operation pending on it.
#. The GC might also get delayed if there is load on the system,
   this is not usually high.
#. The deletion of port also depends on when nova detaches the port
   from SE VM. If there is a lot of load on OpenStack system, the
   messages to nova and neutron might get delayed, hence delaying
   the process of detaching the port from VM.
#. There was an issue in Avi due to which sometimes, the VS goes
   through a state change when VS and its default pool are deleted
   at once. This state change was adding delay to the garbage
   collection process. This issue was seen when LBaaSv2 listener and
   pool are deleted at once through a heat stack or terraform
   template. It is fixed in 18.2.6.


Solution
========
The client deleting the OpenStack LBaaSv2 resource needs to retry the
deletion of OpenStack network in case it fails due to “One or more ports
have an IP allocation from this subnet.”
