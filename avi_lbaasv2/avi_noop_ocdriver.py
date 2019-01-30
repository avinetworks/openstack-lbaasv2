import sys
import traceback
import svc_monitor.services.loadbalancer.drivers.abstract_driver as \
    abstract_driver

from functools import wraps
from svc_monitor.config_db import (LoadbalancerSM, LoadbalancerListenerSM,
                                   LoadbalancerPoolSM, LoadbalancerMemberSM,
                                   HealthMonitorSM)


def cc_trace(f):
    @wraps(f)
    def f_trace(self, *args, **kwargs):
        self.log.info('ocavi fn %s args %s' % (f.__name__, str(args)))
        return f(self, *args, **kwargs)
    return f_trace


def cc_strace(f):
    @wraps(f)
    def f_strace(self, *args, **kwargs):
        self.log.info('ocavi fn %s args %s stack %s' %
                      (f.__name__, str(args), traceback.format_stack()))
        return f(self, *args, **kwargs)
    return f_strace


class OpencontrailAviLoadbalancerDriver(
        abstract_driver.ContrailLoadBalancerAbstractDriver):

    def __init__(self, name, manager, api, db, args=None):
        self._name = name
        self._api = api
        self._svc_manager = manager
        self.db = db
        self.args = args
        self.config = None
        self.log = self._svc_manager.logger
        self.set_config(args.config_sections)

    def _dump(self, f, *args):
        msg = 'ocavi %s args %s ' % (f, str(args))
        for i in args:
            if i is None or isinstance(i, dict):
                continue
            d = dict()
            try:
                d = i.__dict__
            except:  # noqa
                pass
            msg += '\nocavi %s %s %s %s' % (i, type(i), dir(i), d)
        self.log.info(msg)

    def _dump_lb(self, loadbalancer, old_loadbalancer=None):
        f = sys._getframe(1).f_code.co_name
        objid = loadbalancer['id']
        obj = LoadbalancerSM.get(objid)
        self._dump(f, loadbalancer, obj)
        if old_loadbalancer:
            objid = old_loadbalancer['id']
            obj = LoadbalancerSM.get(objid)
            self._dump(f, old_loadbalancer, obj)

    def _dump_ll(self, listener, old_listener=None):
        f = sys._getframe(1).f_code.co_name
        objid = listener['id']
        obj = LoadbalancerListenerSM.get(objid)
        self._dump(f, listener, obj)
        if old_listener:
            objid = old_listener['id']
            obj = LoadbalancerListenerSM.get(objid)
            self._dump(f, old_listener, obj)

    def _dump_pool(self, pool, old_pool=None):
        f = sys._getframe(1).f_code.co_name
        objid = pool['id']
        obj = LoadbalancerPoolSM.get(objid)
        self._dump(f, pool, obj)
        if old_pool:
            objid = old_pool['id']
            obj = LoadbalancerPoolSM.get(objid)
            self._dump(f, old_pool, obj)

    def _dump_member(self, member, old_member=None):
        f = sys._getframe(1).f_code.co_name
        objid = member['id']
        obj = LoadbalancerMemberSM.get(objid)
        self._dump(f, member, obj)
        if old_member:
            objid = old_member['id']
            obj = LoadbalancerMemberSM.get(objid)
            self._dump(f, old_member, obj)

    def _dump_hm(self, pid, hm, old_hm=None):
        f = sys._getframe(1).f_code.co_name
        objid = hm['id']
        obj = HealthMonitorSM.get(objid)
        self._dump(f, pid, hm, obj)
        if old_hm:
            objid = old_hm['id']
            obj = HealthMonitorSM.get(objid)
            self._dump(f, pid, old_hm, obj)

    def set_config(self, config):
        self.config = dict(config.items(self._name))
        self.log.info('ocavi %s config %s' % (self._name, self.config))

    def create_loadbalancer(self, loadbalancer):
        self._dump_lb(loadbalancer)

    def update_loadbalancer(self, old_loadbalancer, loadbalancer):
        self._dump_lb(loadbalancer, old_loadbalancer=old_loadbalancer)

    def delete_loadbalancer(self, loadbalancer):
        self._dump_lb(loadbalancer)

    def create_listener(self, listener):
        self._dump_ll(listener)

    def update_listener(self, old_listener, listener):
        self._dump_ll(listener, old_listener=old_listener)

    def delete_listener(self, listener):
        self._dump_ll(listener)

    def create_pool(self, pool):
        self._dump_pool(pool)

    def update_pool(self, old_pool, pool):
        self._dump_pool(pool, old_pool=old_pool)

    def delete_pool(self, pool):
        self._dump_pool(pool)

    def create_member(self, member):
        self._dump_member(member)

    def update_member(self, old_member, member):
        self._dump_member(member, old_member=old_member)

    def delete_member(self, member):
        self._dump_member(member)

    def create_pool_health_monitor(self, health_monitor, pool_id):
        self._dump_hm(pool_id, health_monitor)

    def update_pool_health_monitor(self, old_health_monitor,
                                   health_monitor, pool_id):
        self._dump_hm(pool_id, health_monitor, old_hm=old_health_monitor)

    def delete_pool_health_monitor(self, health_monitor, pool_id):
        self._dump_hm(pool_id, health_monitor)

    def update_health_monitor(self, id, health_monitor):
        self._dump_hm(id, health_monitor)

    # ignored v1 apis ###
    def set_config_v2(self, lb_id):
        conf = {'version': '16.3.1'}
        return conf

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
