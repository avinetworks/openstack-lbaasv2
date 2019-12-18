import sys
import traceback
import time
import svc_monitor.services.loadbalancer.drivers.abstract_driver as \
    abstract_driver
import neutron_lbaas.common.cert_manager.barbican_cert_manager as nbcm

from functools import wraps
from barbicanclient import client as barbican_client
from keystoneauth1.identity import v2 as v2_client
from keystoneauth1.identity import v3 as v3_client
from keystoneauth1 import session
from svc_monitor.config_db import (LoadbalancerSM, LoadbalancerListenerSM,
                                   LoadbalancerPoolSM, LoadbalancerMemberSM)
# from svc_monitor.config_db import HealthMonitorSM
from svc_monitor.config_db import VirtualMachineInterfaceSM
from avi_lbaasv2.common.avi_client import AviClient
from avi_lbaasv2.common.avi_generic import (update_loadbalancer_obj,
                                            listener_update_avi_vs,
                                            listener_delete_avi_vs,
                                            hm_update_avi_hm,
                                            hm_delete_avi_hm,
                                            pool_update_avi_vs_pool,
                                            pool_delete_avi_vs_pool,
                                            delete_vsvip)
from avi_lbaasv2.common.avi_generic import DriverObjFunctions
from avi_lbaasv2.common.avi_octransform import (transform_loadbalancer_obj,
                                                transform_listener_obj,
                                                transform_member_obj,
                                                transform_hm_obj,
                                                transform_pool_obj,
                                                IdObj, OCLog)
from avi_lbaasv2.common.avi_transform import AviHelper
from avi_lbaasv2.config.avi_config import AVI_OPTS


LOG = None

# debugging


def cc_trace(f):
    @wraps(f)
    def f_trace(self, *args, **kwargs):
        self.log.info('fn %s args %s', f.__name__, str(args))
        try:
            res = f(self, *args, **kwargs)
            return res
        except Exception as e:
            self.log.exception('ocavi %s', e)
            raise e
    return f_trace


def cc_strace(f):
    @wraps(f)
    def f_strace(self, *args, **kwargs):
        self.log.info('fn %s args %s stack %s',
                      f.__name__, str(args), traceback.format_stack())
        return f(self, *args, **kwargs)
    return f_strace


def cc_ignore(f):
    @wraps(f)
    def f_ignore(self, *args, **kwargs):
        self.log.info('ignore fn %s args %s', f.__name__, str(args))
        return
    return f_ignore


def _dump(f, *args):
    msg = 'ocavi %s args %s ' % (f, str(args))
    for i in args:
        if not i:
            continue
        d = dict()
        try:
            d = i.__dict__
        except:  # noqa
            pass
        msg += ' %s %s %s %s' % (i, type(i), dir(i), d)
    LOG.info(msg)


def _dump_objs(*args):
    f = sys._getframe(1).f_code.co_name
    _dump(f, *args)


def _dump_lb(loadbalancer, old_loadbalancer=None):
    f = sys._getframe(1).f_code.co_name
    objid = loadbalancer['id']
    obj = LoadbalancerSM.get(objid)
    _dump(f, loadbalancer, obj)
    if old_loadbalancer:
        objid = old_loadbalancer['id']
        obj = LoadbalancerSM.get(objid)
        _dump(f, old_loadbalancer, obj)


def _dump_ll(listener, old_listener=None):
    f = sys._getframe(1).f_code.co_name
    objid = listener['id']
    obj = LoadbalancerListenerSM.get(objid)
    _dump(f, listener, obj)
    if old_listener:
        objid = old_listener['id']
        obj = LoadbalancerListenerSM.get(objid)
        _dump(f, old_listener, obj)


def _dump_pool(pool, old_pool=None):
    f = sys._getframe(1).f_code.co_name
    objid = pool['id']
    obj = LoadbalancerPoolSM.get(objid)
    _dump(f, pool, obj)
    if old_pool:
        objid = old_pool['id']
        obj = LoadbalancerPoolSM.get(objid)
        _dump(f, old_pool, obj)


def _dump_member(member, old_member=None):
    f = sys._getframe(1).f_code.co_name
    objid = member['id']
    obj = LoadbalancerMemberSM.get(objid)
    _dump(f, member, obj)
    if old_member:
        objid = old_member['id']
        obj = LoadbalancerMemberSM.get(objid)
        _dump(f, old_member, obj)


def _get_ks_session(args, project_id=None):
    kwargs = {
        'auth_url': args.auth_url,
        'username': args.admin_user,
        'password': args.admin_password,
    }
    if args.auth_version in [2, '2', '2.0', 'v2.0', 'v2']:
        client = v2_client
        kwargs['tenant_name'] = args.admin_tenant_name
        if project_id:
            kwargs['tenant_id'] = project_id
    elif args.auth_version in [3, '3', 'v3']:
        client = v3_client
        kwargs['project_name'] = args.admin_tenant_name
        if project_id:
            kwargs['project_id'] = project_id
        kwargs['user_domain_name'] = args.admin_user_domain
        kwargs['project_domain_name'] = args.admin_project_domain
    else:
        raise Exception('Unknown keystone version!')
    kc = client.Password(**kwargs)
    sess = session.Session(auth=kc)
    return sess


def _get_cert_client(args, project_id=None):
    s = _get_ks_session(args, project_id=project_id)
    bc = barbican_client.Client(session=s, region_name=args.region_name)
    return bc


class OpencontrailObjFunctions(DriverObjFunctions):
    def __init__(self, driver):
        self.driver = driver
        self.barbican_clients = dict()

    # loadbalancer
    def loadbalancer_get(self, context, lb_id):
        obj = transform_loadbalancer_obj(self.driver, lb_id, None)
        return obj

    # pool
    def pool_get(self, context, pool_id):
        obj = transform_pool_obj(self.driver, pool_id, None)
        return obj

    # listener
    def listener_get(self, context, ll_id):
        obj = transform_listener_obj(self.driver, ll_id, None)
        return obj

    def listeners_get(self, context, lb, pool=None):
        listeners = []
        for ll_id in lb.loadbalancer_listeners:
            obj = self.listener_get(context, ll_id)
            if not pool or pool.id == obj.default_pool_id:
                listeners.append(obj)
        return listeners

    def cert_get(self, project_id, cert_ref):
        bc = self.barbican_clients.get(project_id)
        if bc is None:
            args = self.driver._svc_manager._args
            bc = _get_cert_client(args, project_id=project_id)
            self.barbican_clients[project_id] = bc
        cert_container = bc.containers.get(container_ref=cert_ref)
        os_cert = nbcm.Cert(cert_container)
        return os_cert


class OpencontrailAviLoadbalancerDriver(
        abstract_driver.ContrailLoadBalancerAbstractDriver):

    def __init__(self, name, manager, api, db, args=None):
        global LOG
        LOG = manager.logger
        self._name = name
        self._api = api
        self._svc_manager = manager
        self.db = db
        self.args = args
        self.conf = IdObj()
        self.log = OCLog(name, manager.logger)
        self.lb_agent = manager.loadbalancer_agent
        self.set_config(args.config_sections)
        self._init_ocavi()
        self.objfns = OpencontrailObjFunctions(self)

    def _init_ocavi(self):
        try:
            self.client = AviClient(self.conf.address, self.conf.user,
                                    self.conf.password,
                                    verify=self.conf.cert_verify, log=self.log)
        except Exception as e:
            self.log.exception(
                'Could not create session to Avi Controller: %s', e)
        self.avi_helper = AviHelper(self.conf, self.log)

    # init

    @cc_trace
    def set_config(self, config):
        avicfg = {i.name: getattr(i, 'default', None) for i in AVI_OPTS}
        avicfg.update(dict(config.items(self._name)))
        for k, v in avicfg.iteritems():
            setattr(self.conf, k, v)
        self.log.info('name %s config %s %s', self._name, self.conf, avicfg)

    # LB APIs ###

    @cc_trace
    def create_loadbalancer(self, loadbalancer):
        # Nothing much to do on a LB creation; we need at least one listener
        pass

    @cc_trace
    def update_loadbalancer(self, old_loadbalancer, loadbalancer):
        lb = transform_loadbalancer_obj(self, loadbalancer['id'], loadbalancer)
        old_lb = transform_loadbalancer_obj(self, old_loadbalancer['id'],
                                            old_loadbalancer)
        _dump_objs(lb, old_lb)
        # disable/enable the VSes of this load balancer to force
        # floating-ip association
        if lb.admin_state_up and old_lb.admin_state_up:
            lb.admin_state_up = False
            update_loadbalancer_obj(self, None, old_lb, lb)
            time.sleep(2.0)
            lb.admin_state_up = True
            old_lb.admin_state_up = False
        update_loadbalancer_obj(self, None, old_lb, lb)

    @cc_trace
    def delete_loadbalancer(self, loadbalancer):
        lb = transform_loadbalancer_obj(self, loadbalancer['id'], loadbalancer)
        delete_vsvip(lb, self.client)

    @cc_trace
    def create_listener(self, listener):
        ll = transform_listener_obj(self, listener['id'], listener)
        _dump_objs(ll)
        listener_update_avi_vs(self, None, ll, "update")

    @cc_trace
    def update_listener(self, old_listener, listener):
        ll = transform_listener_obj(self, listener['id'], listener)
        _dump_objs(ll)
        listener_update_avi_vs(self, None, ll, "update")

    @cc_trace
    def delete_listener(self, listener):
        ll = transform_listener_obj(self, listener['id'], listener,
                                    delete=True)
        _dump_objs(ll)
        listener_delete_avi_vs(self, None, ll)

    @cc_trace
    def create_pool(self, pool):
        p = transform_pool_obj(self, pool['id'], pool)
        _dump_objs(p)
        pool_update_avi_vs_pool(self, None, p, update_ls=True)

    @cc_trace
    def update_pool(self, old_pool, pool):
        p = transform_pool_obj(self, pool['id'], pool)
        _dump_objs(p)
        pool_update_avi_vs_pool(self, None, p)
        old_hms = set(old_pool.get('health_monitors', []))
        new_hms = set(pool.get('health_monitors', []))
        rem_hms = old_hms - new_hms
        for hm_id in rem_hms:
            hm = transform_hm_obj(self, hm_id, None, delete=True)
            if not hm:
                hm = IdObj(id=hm_id, tenant_id=p.tenant_id)
            hm_delete_avi_hm(self, None, hm)

    @cc_trace
    def delete_pool(self, pool):
        p = transform_pool_obj(self, pool['id'], pool, delete=True)
        _dump_objs(p)
        pool_delete_avi_vs_pool(self, None, p)

    @cc_ignore
    def create_member(self, member):
        # update pool is triggered
        # ignore the create_member handling
        pass

    @cc_ignore
    def update_member(self, old_member, member):
        # mostly an update_member will not be invoked
        # update pool is triggered
        pass

    @cc_trace
    def delete_member(self, member):
        m = transform_member_obj(self, member['id'], member, delete=True)
        _dump_objs(m)
        # update pool is triggered

    @cc_trace
    def create_pool_health_monitor(self, health_monitor, pool_id):
        hm = transform_hm_obj(self, health_monitor['id'], health_monitor)
        hm_update_avi_hm(self, None, hm)
        # create_pool_health_monitor - update_pool

    @cc_trace
    def create_health_monitor(self, health_monitor, pool_id):
        self.create_pool_health_monitor(health_monitor, pool_id)

    @cc_trace
    def update_pool_health_monitor(self, old_health_monitor,
                                   health_monitor, pool_id):
        # mostly an update_pool_health_monitor will not be invoked
        hm = transform_hm_obj(self, health_monitor['id'], health_monitor)
        hm_update_avi_hm(self, None, hm)
        # update_hm - create_pool_health_monitor + update pool is triggered

    @cc_trace
    def update_health_monitor(self, *args):
        if len(args) == 2:
            self.update_health_monitor3x(*args)
        elif len(args) == 3:
            self.update_health_monitor4x(*args)
        else:
            pass

    def update_health_monitor4x(self, old_health_monitor, health_monitor,
                                pool_id):
        self.update_pool_health_monitor(old_health_monitor,
                                        health_monitor, pool_id)

    @cc_trace
    def delete_pool_health_monitor(self, health_monitor, pool_id):
        # mostly a delete_pool_health_monitor will not be invoked
        # delete_hm - update pool is triggered
        hm = transform_hm_obj(self, health_monitor['id'], health_monitor,
                              delete=True)
        hm_delete_avi_hm(self, None, hm)

    @cc_trace
    def delete_health_monitor(self, health_monitor, pool_id):
        self.delete_pool_health_monitor(health_monitor, pool_id)

    def update_health_monitor3x(self, id, health_monitor):
        hm = transform_hm_obj(self, id, health_monitor)
        hm_update_avi_hm(self, None, hm)

    def set_config_v2(self, lb_id):
        try:
            vmi_id = LoadbalancerSM.get(lb_id).virtual_machine_interface
            vmi = VirtualMachineInterfaceSM.get(vmi_id)
            fips = vmi.floating_ips
            return str(fips)
        except Exception as e:
            self.log.exception("set_config_v2 failed: %s", e)
            pass

    # ignored APIs ###

    def set_config_v1(self, pool_id):
        pass

    def stats(self, pool_id):
        pass

    def create_vip(self, vip):
        pass

    def update_vip(self, old_vip, vip):
        pass

    def delete_vip(self, vip):
        pass
