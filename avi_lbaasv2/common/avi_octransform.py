
import copy
import logging
from svc_monitor.config_db import (LoadbalancerSM, LoadbalancerListenerSM,
                                   LoadbalancerPoolSM, LoadbalancerMemberSM,
                                   HealthMonitorSM)

# transforms

OBJDICT_ATTRS = {
    'id': None,
    'name': None,
    'tenant_id': None,
    'description': None,
    'admin_state_up': None,
    'status': 'provisioning_status',
}

OBJPROP_ATTRS = {
    'admin_state': 'admin_state_up',
}

LB_OBJDICT_ATTRS = {
    'subnet_id': 'vip_subnet_id',
    'address': 'vip_address',
    'port_id': 'vip_port_id',
}

LL_OBJDICT_ATTRS = {
    'protocol_port': None,
    'protocol': None,
    'connection_limit': None,
    'default_tls_container': 'default_tls_container_id',
}

P_OBJDICT_ATTRS = {
    'lb_method': 'lb_algorithm',
    'protocol': None,
    'loadbalancer_id': None,
}

M_OBJDICT_ATTRS = {
    'address': None,
    'protocol_port': None,
    'weight': None,
}

HM_OBJDICT_ATTRS = {
    'type': None,
    'delay': None,
    'timeout': None,
    'max_retries': None,
    'http_method': None,
    'url_path': None,
    'expected_codes': None,
}


class IdObj(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)


class OCLogHandler(logging.Handler):
    def __init__(self, name, svcmon_log, level=logging.INFO):
        super(OCLogHandler, self).__init__(level=level)
        self.logger = svcmon_log
        self.name = name
        self.level_fnmap = {
            logging.DEBUG: self.logger.debug,
            logging.INFO: self.logger.info,
            logging.WARNING: self.logger.warning,
            logging.ERROR: self.logger.error,
            logging.CRITICAL: self.logger.critical,
        }

    def emit(self, record):
        levelno = record.levelno
        msg = self.format(record)
        logfn = self.level_fnmap.get(levelno, self.logger.info)
        logfn('%s %s' % (self.name, msg))


class OCLog(logging.Logger):
    def __init__(self, name, svcmon_log, level=logging.INFO):
        super(OCLog, self).__init__(name, level=level)
        self.propagate = False
        self.addHandler(OCLogHandler(name, svcmon_log, level=level))


def _transform_attrs(obj, dictprop, attrs, ):
    for ock, nk in attrs.iteritems():
        nk = (nk or ock)
        v = dictprop.get(ock)
        setattr(obj, nk, v)


def _transform_obj(obj, objdict):
    if objdict:
        _transform_attrs(obj, objdict, OBJDICT_ATTRS)
    # from params
    props = getattr(obj, 'params', None)
    if props:
        _transform_attrs(obj, props, OBJPROP_ATTRS)
    return obj


def transform_loadbalancer_obj(driver, objid, objdict, delete=False):
    obj = LoadbalancerSM.get(objid)
    if not obj:
        return None
    if delete and obj.id_perms:
        obj.id_perms['enable'] = False
        if objdict:
            objdict['status'] = 'PENDING_DELETE'
    obj = copy.deepcopy(obj)
    if not objdict:
        objdict = driver.lb_agent.loadbalancer_get_reqdict(obj)
    _transform_obj(obj, objdict)
    _transform_attrs(obj, objdict, LB_OBJDICT_ATTRS)
    # ls ids
    llobjs = [IdObj(id=ll_id) for ll_id in obj.loadbalancer_listeners]
    setattr(obj, 'listeners', llobjs)
    return obj


def _get_lbobj(driver, objdict):
    lbid = objdict['loadbalancer_id']
    xlbobj = transform_loadbalancer_obj(driver, lbid, None)
    return xlbobj


def transform_listener_obj(driver, objid, objdict, delete=False):
    obj = LoadbalancerListenerSM.get(objid)
    if not obj:
        return None
    if delete and obj.id_perms:
        obj.id_perms['enable'] = False
        if objdict:
            objdict['status'] = 'PENDING_DELETE'
    obj = copy.deepcopy(obj)
    if not objdict:
        objdict = driver.lb_agent.listener_get_reqdict(obj)
    _transform_obj(obj, objdict)
    _transform_attrs(obj, objdict, LL_OBJDICT_ATTRS)
    # lb embed
    xlbobj = _get_lbobj(driver, objdict)
    setattr(obj, 'loadbalancer', xlbobj)
    # def pool id and embed
    def_pid = obj.loadbalancer_pool
    pobj = LoadbalancerPoolSM.get(def_pid) if def_pid else None
    xpobj = None
    if pobj:
        pobj = copy.deepcopy(pobj)
        pdict = driver.lb_agent.loadbalancer_pool_get_reqdict(pobj)
        xpobj = transform_pool_obj(driver, pdict['id'], pdict)
    setattr(obj, 'default_pool_id', def_pid)
    setattr(obj, 'default_pool', xpobj)
    # sni ids
    snids = objdict.get('sni_containers', list())
    sniobjs = [IdObj(tls_container_id=i) for i in snids]
    setattr(obj, 'sni_containers', sniobjs)
    return obj


def transform_member_obj(driver, objid, objdict, delete=False):
    obj = LoadbalancerMemberSM.get(objid)
    if not obj:
        return None
    if delete and obj.id_perms:
        obj.id_perms['enable'] = False
        if objdict:
            objdict['status'] = 'PENDING_DELETE'
    obj = copy.deepcopy(obj)
    if not objdict:
        objdict = driver.lb_agent.loadbalancer_member_get_reqdict(obj)
    _transform_obj(obj, objdict)
    _transform_attrs(obj, objdict, M_OBJDICT_ATTRS)
    return obj


def transform_hm_obj(driver, objid, objdict, delete=False):
    obj = HealthMonitorSM.get(objid)
    if not obj:
        return None
    if delete and obj.id_perms:
        obj.id_perms['enable'] = False
        if objdict:
            objdict['status'] = 'PENDING_DELETE'
    obj = copy.deepcopy(obj)
    if not objdict:
        objdict = driver.lb_agent.hm_get_reqdict(obj)
    _transform_obj(obj, objdict)
    _transform_attrs(obj, objdict, HM_OBJDICT_ATTRS)
    return obj


def transform_pool_obj(driver, objid, objdict, delete=False):
    obj = LoadbalancerPoolSM.get(objid)
    if not obj:
        return None
    if delete and obj.id_perms:
        obj.id_perms['enable'] = False
        if objdict:
            objdict['status'] = 'PENDING_DELETE'
    obj = copy.deepcopy(obj)
    if not objdict:
        objdict = driver.lb_agent.loadbalancer_pool_get_reqdict(obj)
    _transform_obj(obj, objdict)
    _transform_attrs(obj, objdict, P_OBJDICT_ATTRS)
    # lb embed
    xlbobj = _get_lbobj(driver, objdict)
    setattr(obj, 'root_loadbalancer', xlbobj)
    # members embed
    mobjs = set()
    for mid in objdict['members']:
        mobj = transform_member_obj(driver, mid, None)
        if mobj:
            mobjs.add(mobj)
    setattr(obj, 'members', mobjs)
    # hm embed
    hmid = next(iter(objdict['health_monitors']), None)
    hmobj = transform_hm_obj(driver, hmid, None) if hmid else None
    setattr(obj, 'healthmonitor', hmobj)
    # persist
    prst = objdict.get('session_persistence')
    prstobj = None
    if prst:
        prstobj = IdObj(type=prst['type'], cookie_name=prst['cookie_name'])
    setattr(obj, 'session_persistence', prstobj)
    return obj
