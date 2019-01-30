import ast
import logging
import neutron_lbaas.common.cert_manager as ncm
import time

from oslo_config import cfg
from oslo_utils import excutils

from avi_lbaasv2.avi_client import AviClient
from avi_lbaasv2.avi_transform import AviHelper
from avi_lbaasv2.avi_api import APIError
from avi_lbaasv2.avi_generic import (
    update_loadbalancer_obj,
    listener_update_avi_vs, listener_delete_avi_vs,
    hm_update_avi_hm, hm_delete_avi_hm,
    pool_update_avi_vs_pool, pool_delete_avi_vs_pool,
    member_op_avi_pool, hm_op_avi_pool)
from avi_lbaasv2.avi_generic import DriverObjFunctions
from avi_lbaasv2 import avi_config

from neutron_lbaas.services.loadbalancer import constants as lb_constants
from neutron_lbaas.drivers import driver_base

prov = avi_config.AVI_PROV.lower()
cfg.CONF.register_opts(avi_config.AVI_OPTS, prov)
CONF = cfg.CONF.get(prov)
LOG = logging.getLogger(__name__)

#            from IPython.core.debugger import Pdb
#            pdb = Pdb()
#            pdb.set_trace()

is_contrail = None

# Try to import neutron objects, they are available from release >
# Newton. Otherwise, try to import neutron manager
obj_flavors = None
neutron_manager = None
try:
    from neutron.objects import flavor as obj_flavor
    obj_flavors = True
except ImportError as err:
    LOG.error(err)
    obj_flavors = False

if not obj_flavors:
    try:
        from neutron import manager
        from neutron.plugins.common import constants
        from neutron.services.flavors import flavors_plugin
        neutron_manager = True
    except ImportError as err:
        LOG.error(err)
        LOG.warn("Couldn't import Neutron modules, Flavors will not work")
        neutron_manager = False


class LoadBalancerManager(driver_base.BaseLoadBalancerManager):
    def __init__(self, driver):
        super(LoadBalancerManager, self).__init__(driver)
        self.driver = driver

    def _detect_plugin(self):
        global is_contrail
        if is_contrail is None:
            is_contrail = False
            try:
                core = self.driver.plugin.db._core_plugin.delete_port.im_class
                if core and 'contrail' in str(core).lower():
                    is_contrail = True
                    LOG.debug('detected contrail plugin')
            except:  # noqa
                pass
        return

    def create(self, context, lb):
        self._detect_plugin()
        LOG.debug("Avi driver create lb: %s", repr(lb))
        flvid = getattr(lb, 'flavor_id', None)
        if flvid:
            metainfo = self.driver.objfns.get_metainfo_from_flavor(
                context, flvid)
            LOG.info("LB metainfo from flavor %s", metainfo)
        # Nothing much to do on a LB creation; we need at least one listener
        self.successful_completion(context, lb)

    def update(self, context, old_lb, lb):
        LOG.debug("Avi driver update lb: %s", repr(lb))
        failed = update_loadbalancer_obj(self.driver, context, old_lb, lb)
        if not failed:
            self.successful_completion(context, lb)
        else:
            self.failed_completion(context, lb)

    def delete(self, context, lb):
        self._detect_plugin()
        LOG.debug("Avi driver delete lb: %s", repr(lb))
        if is_contrail:
            vportid = lb.vip_port_id
            if vportid:
                self.driver.plugin.db._core_plugin.delete_port(context,
                                                               vportid)
                LOG.debug('deleted LB vip port %s', vportid)

        # AV-35351: Can't determine how much time it would take to
        # delete all the associated ports for this load balancer. It
        # depends on types of VSes (SSL etc) and number of VSes.
        # All ports will be deleted _eventually_; no need to
        # wait for them.
        # LOG.info('await ports cleanup for Avi VSes')
        time.sleep(2)
        self.successful_completion(context, lb, delete=True)

    def refresh(self, context, lb):
        LOG.debug("Avi driver refresh lb: %s", repr(lb))
        for listener in self.get_listeners(context, lb):
            self.driver.listener.update(context, None, listener)
        # self.update(context, lb, lb)

    def stats(self, context, lb):
        LOG.debug("Avi driver stats of lb: %s", repr(lb))
        # TODO(ypraveen) Return real stats
        stats = {
            lb_constants.STATS_IN_BYTES: 0,
            lb_constants.STATS_OUT_BYTES: 0,
            lb_constants.STATS_ACTIVE_CONNECTIONS: 0,
            lb_constants.STATS_TOTAL_CONNECTIONS: 0,
        }
        return stats


class ListenerManager(driver_base.BaseListenerManager):

    def __init__(self, driver):
        super(ListenerManager, self).__init__(driver)
        self.driver = driver

    def create(self, context, listener):
        LOG.debug("Avi driver create listener: %s", repr(listener))
        try:
            listener_update_avi_vs(self.driver, context, listener, "create")
            self.successful_completion(context, listener)
        except APIError as e:
            LOG.exception("Creating VirtualService on Avi Failed: %s, %s",
                          listener.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, listener)

    def update(self, context, old_listener, listener):
        LOG.debug("Avi driver update listener: %s", repr(listener))
        try:
            listener_update_avi_vs(self.driver, context, listener, "update")
            self.successful_completion(context, listener)
        except APIError as e:
            LOG.exception("Updating VirtualService on Avi Failed: %s, %s",
                          listener.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, listener)

    def delete(self, context, listener):
        LOG.debug("Avi driver delete listener: %s", repr(listener))
        try:
            listener_delete_avi_vs(self.driver, context, listener)
            self.successful_completion(context, listener, delete=True)
        except Exception as e:
            LOG.exception("Deleting VirtualService on Avi Failed: %s, %s",
                          listener.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, listener)


class PoolManager(driver_base.BasePoolManager):

    def __init__(self, driver):
        super(PoolManager, self).__init__(driver)
        self.driver = driver

    def create(self, context, pool):
        LOG.debug("Avi driver create pool: %s", repr(pool))
        # we will create one pool for each listener
        try:
            pool_update_avi_vs_pool(self.driver, context, pool, update_ls=True)
            self.successful_completion(context, pool)
        except APIError as e:
            LOG.exception("Creating Pool on Avi Failed: %s, %s", e, pool.id)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, pool)

    def update(self, context, old_pool, pool):
        LOG.debug("Avi driver update pool: %s", repr(pool))
        try:
            pool_update_avi_vs_pool(self.driver, context, pool)
            self.successful_completion(context, pool)
        except APIError as e:
            LOG.exception("Updating Pool on Avi Failed: %s, %s", e, pool.id)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, pool)

    def delete(self, context, pool):
        LOG.debug("Avi driver delete pool: %s", repr(pool))
        # remove the pool from all VSes first
        try:
            pool_delete_avi_vs_pool(self.driver, context, pool)
            self.successful_completion(context, pool, delete=True)
        except APIError as e:
            LOG.exception("Deleting Pool on Avi Failed: %s, %s", e, pool.id)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, pool)


class MemberManager(driver_base.BaseMemberManager):

    def __init__(self, driver):
        super(MemberManager, self).__init__(driver)
        self.driver = driver

    def member_op(self, context, member, action="add"):
        try:
            member_op_avi_pool(self.driver, context, member, action=action)
            self.successful_completion(context, member,
                                       delete=(action == "delete"))
        except APIError as e:
            LOG.exception("%s of Member on Avi Failed: %s, %s", action,
                          member.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, member)

    def update_pool(self, context, member, action):
        try:
            pool_update_avi_vs_pool(self.driver, context, member.pool)
            self.successful_completion(context, member,
                                       delete=(action == "delete"))
        except APIError as e:
            LOG.exception("%s of Member on Avi Failed: %s, %s", action,
                          member.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, member)

    def create(self, context, member):
        LOG.debug("Avi driver create member: %s", repr(member))
        if self.driver.conf.use_placement_network_for_pool:
            # PATCH isn't working for placement network; avi bug;
            # do PUT on pool
            self.update_pool(context, member, "add")
        else:
            # This will PATCH pool members
            self.member_op(context, member, action="add")

    def update(self, context, old_member, member):
        LOG.debug("Avi driver update member: %s", repr(member))
        # IP address and port number fields are read-only attributes
        # and thus can't be changed; since those fields form the key
        # on Avi, we can simply use "add" to perform update.
        if self.driver.conf.use_placement_network_for_pool:
            # PATCH isn't working for placement network; avi bug;
            # do PUT on pool
            self.update_pool(context, member, "add")
        else:
            # This will PATCH pool members
            self.member_op(context, member, action="add")

    def delete(self, context, member):
        LOG.debug("Avi driver delete member: %s", repr(member))
        if self.driver.conf.use_placement_network_for_pool:
            # PATCH isn't working for placement network; avi bug;
            # do PUT on pool
            self.update_pool(context, member, "delete")
        else:
            # This will PATCH pool members
            self.member_op(context, member, action="delete")


class HealthMonitorManager(driver_base.BaseHealthMonitorManager):

    def __init__(self, driver):
        super(HealthMonitorManager, self).__init__(driver)
        self.driver = driver

    def get_pools(self, context, health_monitor):
        db_pools = []
        pools = []
        # two different ways to get pools, depending on the version of
        # OpenStack
        #    liberty -- health_monitor has only one pool at a time
        #    mitaka -- health_monitor could be used by multiple pools
        if hasattr(health_monitor, "pool"):
            if health_monitor.pool:
                pools.append(health_monitor.pool)
        else:
            try:
                loadbalancer = health_monitor.root_loadbalancer
                pools = loadbalancer.pools
            except Exception as e:
                LOG.exception("Could not get pools: %s, %s", health_monitor, e)
        for pool in pools:
            if pool.healthmonitor_id == health_monitor.id:
                db_pool = self.driver.plugin.db.get_pool(
                    context, id=pool.id)
                db_pools.append(db_pool)
        return db_pools

    def create(self, context, health_monitor):
        LOG.debug("Avi driver create pool_health_monitor. "
                  "health_monitor.type: %s",
                  health_monitor.type)
        try:
            hm_update_avi_hm(self.driver, context, health_monitor)
            for pool in self.get_pools(context, health_monitor):
                try:
                    # pool_update_avi_vs_pool(self.driver, context, pool)
                    hm_op_avi_pool(self.driver, context, health_monitor,
                                   pool, action="add")
                except Exception as e:
                    LOG.error('Failed to update avi pool %s with HM %s: %s',
                              pool.id, health_monitor.id, e)
            self.successful_completion(context, health_monitor)
        except Exception as e:
            LOG.exception("Creating HealthMonitor failed: %s, %s",
                          health_monitor.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, health_monitor)

    def update(self, context, old_health_monitor, health_monitor):
        LOG.debug("Avi driver update health_monitor: %s",
                  repr(health_monitor))
        try:
            hm_update_avi_hm(self.driver, context, health_monitor)
            for pool in self.get_pools(context, health_monitor):
                try:
                    # pool_update_avi_vs_pool(self.driver, context, pool)
                    hm_op_avi_pool(self.driver, context, health_monitor,
                                   pool, action="add")
                except Exception as e:
                    LOG.error('Failed to update avi pool %s with HM %s: %s',
                              pool.id, health_monitor.id, e)
            self.successful_completion(context, health_monitor)
        except Exception as e:
            LOG.exception("Updating HealthMonitor failed: %s, %s",
                          health_monitor.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, health_monitor)

    def delete(self, context, health_monitor):
        LOG.debug("Avi driver delete health_monitor: %s",
                  repr(health_monitor))
        try:
            for pool in self.get_pools(context, health_monitor):
                # pool_update_avi_vs_pool(self.driver, context, pool)
                hm_op_avi_pool(self.driver, context, health_monitor,
                               pool, action="delete")
            hm_delete_avi_hm(self.driver, context, health_monitor)
            self.successful_completion(context, health_monitor, delete=True)
        except Exception as e:
            LOG.exception("Deleting HealthMonitor failed: %s, %s",
                          health_monitor.id, e)
            with excutils.save_and_reraise_exception():
                self.failed_completion(context, health_monitor)


class NeutronObjFunctions(DriverObjFunctions):
    def __init__(self, driver):
        self.driver = driver

    def get_vip_subnet_from_listener(self, context, ll_id):
        ll = self.listener_get(context, ll_id)
        lb = self.loadbalancer_get(context, ll.loadbalancer_id)
        return lb.vip_subnet_id

    def loadbalancer_get(self, context, lb_id):
        obj = self.driver.plugin.db.get_loadbalancer(context, id=lb_id)
        return obj

    def pool_get(self, context, pool_id):
        obj = self.driver.plugin.db.get_pool(context, id=pool_id)
        return obj

    def listener_get(self, context, ll_id):
        obj = self.driver.plugin.db.get_listener(context, id=ll_id)
        return obj

    def listeners_get(self, context, lb, pool=None):
        listeners = []
        for ll in lb.listeners:
            if not pool or pool.id == ll.default_pool_id:
                obj = self.listener_get(context, ll.id)
                listeners.append(obj)
        return listeners

    def cert_get(self, project_id, cert_ref):
        prov = 'Neutron LBaaS v2 Avi provider'
        CERT_MANAGER_PLUGIN = ncm.get_backend()
        cert_manager = CERT_MANAGER_PLUGIN.CertManager()
        os_cert = cert_manager.get_cert(
            project_id=project_id,
            cert_ref=cert_ref,
            resource_ref=None,  # required arg for mitaka+
            check_only=True,
            service_name=prov)
        return os_cert

    def get_metainfo_from_flavor(self, context, flvid):
        global obj_flavors, neutron_manager
        sp_obj, sp_meta = None, None
        if obj_flavors:
            objs = obj_flavor.FlavorServiceProfileBinding.get_objects(
                context, flavor_id=flvid)
            if not objs:
                LOG.warn("No service profile found for flavor: %s", flvid)
                return {}

            sp_obj = obj_flavor.ServiceProfile.get_object(
                context, id=objs[0].service_profile_id)
            sp_meta = sp_obj.metainfo
        elif neutron_manager:
            plugin = manager.NeutronManager.get_service_plugins().get(
                constants.FLAVORS)
            if not plugin:
                LOG.warn("Flavor plugin not found")
                return {}

            # Will raise FlavorNotFound if doesn't exist
            fl_db = flavors_plugin.FlavorsPlugin.get_flavor(
                plugin, context, flvid)
            if not fl_db:
                LOG.warn("No flavor found for id: %s", flvid)
                return {}

            sp_obj = None
            sp_objs = fl_db.get('service_profiles', None)
            sp_obj_id = sp_objs[0] if sp_objs else None
            if not sp_obj_id:
                LOG.warn("No service profiles associated with flvid: %s",
                         flvid)
                return {}

            sp_obj = flavors_plugin.FlavorsPlugin.get_service_profile(
                plugin, context, sp_obj_id)
            if not sp_obj:
                LOG.warn("No service profiles found with ID: %s",
                         sp_obj_id)
                return {}

            sp_meta = sp_obj.get('metainfo', None)
        else:
            LOG.warn("Couldn't get flavor info")
            return {}

        LOG.debug("SP Obj: %s", sp_obj)
        metainfo = {}
        if sp_meta:
            try:
                metainfo = ast.literal_eval(sp_meta)
            except Exception as e:
                LOG.warn("Error parsing metainfo from SP object %s; error %s",
                         sp_obj, e)

        return metainfo

    def subnet_get(self, context, snwid):
        snw = None
        try:
            snw = self.driver.plugin.db._core_plugin.get_subnet(context, snwid)
        except Exception as e:
            LOG.exception("Could not get subnet %s, error: %s", snwid, e)

        return snw


class AviDriver(driver_base.LoadBalancerBaseDriver):

    def __init__(self, plugin):
        self.plugin = plugin
        self.conf = CONF
        super(AviDriver, self).__init__(self.plugin)
        self.client = None
        try:
            self.client = AviClient(self.conf.address,
                                    self.conf.user,
                                    self.conf.password,
                                    verify=self.conf.cert_verify)
        except Exception as e:
            LOG.exception("Could not create session to Avi Controller: %s", e)
        self.avi_helper = AviHelper(self.conf)
        self.objfns = NeutronObjFunctions(self)
        self.load_balancer = LoadBalancerManager(self)
        self.listener = ListenerManager(self)
        self.pool = PoolManager(self)
        self.member = MemberManager(self)
        self.health_monitor = HealthMonitorManager(self)
        self.log = LOG
