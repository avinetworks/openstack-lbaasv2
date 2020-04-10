import netaddr
import uuid
from avi_lbaasv2.avi_api.avi_api import ObjectNotFound

AVI_DELIM = '-'


class DriverObjFunctions(object):
    def __init__(self, driver):
        self.driver = driver

    def pool_get(self, context, pool_id):
        pass

    def listener_get(self, context, ll_id):
        pass

    def listeners_get(self, context, lb, pool=None):
        pass

    def cert_get(self, project_id, cert_ref):
        pass


def os2avi_uuid(obj_type, eid):
    uid = str(uuid.UUID(eid))
    return obj_type + AVI_DELIM + uid


def update_loadbalancer_obj(driver, context, old_lb, lb):
    failed = False
    try:
        loadbalancer_update_avi_vsvip(driver, old_lb, lb)
    except Exception as e:
        driver.log.exception('ocavi: Could not update loadbalancer: %s, %s',
                             lb, e)
        failed = True

    if failed:
        return failed

    # if there is name change, change the name of vses
    if lb.name == old_lb.name:
        # nothing else to update
        return failed

    listeners = driver.objfns.listeners_get(context, lb)
    for listener in listeners:
        try:
            listener_update_avi_vs(driver, context, listener, 'update')
        except Exception as e:
            driver.log.exception('ocavi: Could not update listener: %s, %s',
                                 listener, e)
            failed = True

    return failed


def loadbalancer_update_avi_vsvip(driver, old_lb, lb):
    if (lb.name == old_lb.name and
            lb.admin_state_up == old_lb.admin_state_up):
        # nothing changed to update remote
        return

    avi_client = driver.client
    vsvip_uuid = form_vsvip_uuid(lb.id)
    avi_tenant_uuid = os2avi_uuid("tenant", lb.tenant_id)
    try:
        vsvip = avi_client.get("vsvip", vsvip_uuid, avi_tenant_uuid)
    except ObjectNotFound:
        return

    res = update_vsvip(lb, avi_client, avi_tenant_uuid, driver.conf.cloud,
                       vsvip=vsvip)
    if res:
        driver.log.debug("Updated vsvip[%s] response: %s ", vsvip['name'],
                         res)


def listener_update_avi_vs(driver, context, listener, op):
    '''
    :param listener:
    :param context:
    :type op: should be 'create' or 'update'
    '''
    client = driver.client
    avi_vs = driver.avi_helper.transform_os_listener_to_avi_vs(
        context, listener, driver)
    avi_tenant_uuid = os2avi_uuid('tenant', listener.tenant_id)
    avi_vs_id = os2avi_uuid('virtualservice', listener.id)
    child_vses = avi_vs.pop('child_vses', [])
    if child_vses:
        avi_vs['type'] = 'VS_TYPE_VH_PARENT'
    else:
        avi_vs['type'] = 'VS_TYPE_NORMAL'
    # create/update parent VS
    if op == 'create':
        pvs = client.create('virtualservice', avi_vs, avi_tenant_uuid)
    else:  # if op == 'update':
        avi_vs.pop('vrf_context_ref', None)  # Don't update VRF Context
        client.update('virtualservice', avi_vs_id, avi_vs, avi_tenant_uuid)
        # update doesn't return vh_child_vs_uuid.. so need to do an
        # explicit get; will remove this once we fix avi api
        pvs = client.get('virtualservice', avi_vs_id, avi_tenant_uuid)

    expected_child_vses = [cvs['uuid'] for cvs in child_vses]
    for existing_child in pvs.get('vh_child_vs_uuid', []):
        if existing_child not in expected_child_vses:
            _delete_avi_vs_pool(driver, existing_child, avi_tenant_uuid)

    if not child_vses:
        return pvs

    # remove inapplicable fields
    for f in ['ip_address', 'address', 'port_uuid',
              'subnet_uuid', 'services', 'port',
              'enable_ssl', 'performance_limits',
              'vip', 'vsvip_ref']:
        avi_vs.pop(f, None)

    avi_vs['type'] = 'VS_TYPE_VH_CHILD'
    avi_vs['vh_parent_vs_ref'] = pvs['url']
    for cvs in child_vses:
        avi_vs['ssl_key_and_certificate_refs'] = [cvs['url']]
        avi_vs['uuid'] = cvs['uuid']
        avi_vs['pool_ref'] = cvs['pool_ref']
        avi_vs['vh_domain_name'] = [cvs['certificate']['subject'][
            'common_name']]
        avi_vs['name'] += '-%s' % (avi_vs['vh_domain_name'])
        if avi_vs['uuid'] in pvs.get('vh_child_vs_uuid', []):
            client.update('virtualservice', avi_vs['uuid'], avi_vs,
                          avi_tenant_uuid)
        else:
            client.create('virtualservice', avi_vs, avi_tenant_uuid)
    return pvs


def _delete_avi_vs_pool(driver, vs_id, avi_tenant_uuid):
    client = driver.client
    try:
        evs = client.get('virtualservice', vs_id, avi_tenant_uuid)
    except ObjectNotFound:
        return
    client.delete('virtualservice', vs_id, avi_tenant_uuid)
    if evs.get('pool_ref', None):
        client.delete('pool', evs['pool_ref'].split('/')[-1],
                      avi_tenant_uuid)
    return


def listener_delete_avi_vs(driver, context, listener):
    # try deleting it from Avi
    avi_vs_id = os2avi_uuid('virtualservice', listener.id)
    avi_tenant_uuid = os2avi_uuid('tenant', listener.tenant_id)

    # delete child VSes if any
    if listener.sni_containers:
        for sc in listener.sni_containers:
            avi_cvs_id = driver.avi_helper.get_avi_sni_vs_uuid(
                sc.tls_container_id, listener.id)
            _delete_avi_vs_pool(driver, avi_cvs_id, avi_tenant_uuid)

    # delete parent VS and pool (if it exists)
    _delete_avi_vs_pool(driver, avi_vs_id, avi_tenant_uuid)
    return


def hm_update_avi_hm(driver, context, health_monitor):
    client = driver.client
    avi_tenant_uuid = os2avi_uuid('tenant', health_monitor.tenant_id)
    avi_hm_def = driver.avi_helper.transform_os_hm_to_avi_hm(health_monitor)
    client.update('healthmonitor', avi_hm_def['uuid'],
                  avi_hm_def, avi_tenant_uuid)


def hm_delete_avi_hm(driver, context, health_monitor):
    client = driver.client
    avi_hm_uuid = os2avi_uuid('healthmonitor', health_monitor.id)
    avi_tenant_uuid = os2avi_uuid('tenant', health_monitor.tenant_id)
    client.delete('healthmonitor', avi_hm_uuid, avi_tenant_uuid)


def pool_update_avi_vs_pool(driver, context, pool, update_ls=False):
    client = driver.client
    avi_helper = driver.avi_helper
    avi_tenant_uuid = os2avi_uuid('tenant', pool.tenant_id)
    avi_pool = driver.avi_helper.transform_os_pool_to_avi_pool(pool, client,
                                                               context, driver)
    listeners = driver.objfns.listeners_get(context, pool.root_loadbalancer,
                                            pool=pool)
    for listener in listeners:
        if listener.default_pool_id != pool.id:
            continue
        avi_helper.fill_avi_pool_uuid_name(avi_pool, pool, listener.id)
        if not update_ls:
            # While updating pool don't update vrf_context_ref
            avi_pool.pop('vrf_ref', None)

        client.update('pool', avi_pool['uuid'], avi_pool, avi_tenant_uuid)
        if update_ls:
            update_avi_vs_pool(driver, avi_tenant_uuid, listener.id,
                               avi_pool["uuid"], action="add")
        for snic in listener.sni_containers:
            owner_id = avi_helper.get_avi_sni_vs_uuid(
                snic.tls_container_id, listener.id)[15:]
            avi_helper.fill_avi_pool_uuid_name(avi_pool, pool, owner_id)
            client.update('pool', avi_pool['uuid'], avi_pool, avi_tenant_uuid)
            if update_ls:
                update_avi_vs_pool(driver, avi_tenant_uuid, owner_id,
                                   avi_pool["uuid"], action="add")


# action: one of {add, delete}
def update_avi_vs_pool(driver, avi_tenant_uuid, os_owner_id,
                       avi_pool_uuid, action="add"):
    client = driver.client
    data = {action: {"pool_ref": "/api/pool/" + avi_pool_uuid}}
    avi_vs_uuid = os2avi_uuid("virtualservice", os_owner_id)
    try:
        client.patch("virtualservice", avi_vs_uuid, data, avi_tenant_uuid,
                     ignore_non_existent_object=(action == "delete"),
                     ignore_non_existent_tenant=(action == "delete"))
    except ObjectNotFound:
        driver.log.exception("ocavi: Avi VS doesn't exist: %s; data: %s; "
                             "tenant: %s", avi_vs_uuid, data, avi_tenant_uuid)
    return


def pool_delete_avi_vs_pool(driver, context, pool):
    client = driver.client
    avi_helper = driver.avi_helper
    avi_tenant_uuid = os2avi_uuid('tenant', pool.tenant_id)
    listeners = driver.objfns.listeners_get(context, pool.root_loadbalancer,
                                            pool=pool)
    for listener in listeners:
        if listener.default_pool_id != pool.id:
            continue
        avi_pool_id = avi_helper.get_avi_pool_uuid(pool.id, listener.id)
        update_avi_vs_pool(driver, avi_tenant_uuid, listener.id, avi_pool_id,
                           action="delete")
        client.delete('pool', avi_pool_id, avi_tenant_uuid)
        for snic in listener.sni_containers:
            owner_id = avi_helper.get_avi_sni_vs_uuid(
                snic.tls_container_id, listener.id)[15:]
            avi_pool_id = avi_helper.get_avi_pool_uuid(pool.id, owner_id)
            update_avi_vs_pool(driver, avi_tenant_uuid, owner_id, avi_pool_id,
                               action="delete")
            client.delete('pool', avi_pool_id, avi_tenant_uuid)

    # delete any application persistence profile
    perst_uuid = os2avi_uuid("applicationpersistenceprofile", pool.id)
    client.delete("applicationpersistenceprofile", perst_uuid, avi_tenant_uuid)


def _get_avi_pool_uuids(driver, context, pool):
    avi_pool_uuids = []
    avi_helper = driver.avi_helper
    listeners = driver.objfns.listeners_get(context, pool.root_loadbalancer,
                                            pool=pool)
    for listener in listeners:
        avi_pool_id = avi_helper.get_avi_pool_uuid(pool.id, listener.id)
        avi_pool_uuids.append(avi_pool_id)
        for snic in listener.sni_containers:
            owner_id = avi_helper.get_avi_sni_vs_uuid(
                snic.tls_container_id, listener.id)[15:]
            avi_pool_id = avi_helper.get_avi_pool_uuid(pool.id, owner_id)
            avi_pool_uuids.append(avi_pool_id)
    return avi_pool_uuids


def member_op_avi_pool(driver, context, member, action="add"):
    client = driver.client
    avi_tenant_uuid = os2avi_uuid("tenant", member.tenant_id)
    avi_pool_uuids = _get_avi_pool_uuids(driver, context, member.pool)
    avi_member, _ = driver.avi_helper.transform_member(member, member.pool,
                                                       context=context,
                                                       driver=driver)
    data = {action: {'servers': [avi_member]}}
    for avi_pool_id in avi_pool_uuids:
        client.patch('pool', avi_pool_id, data, avi_tenant_uuid,
                     ignore_non_existent_object=(action == "delete"),
                     ignore_non_existent_tenant=(action == "delete"),
                     ignore_existing_object=(action == "add"))


def hm_op_avi_pool(driver, context, hm, pool, action="add"):
    client = driver.client
    avi_tenant_uuid = os2avi_uuid("tenant", hm.tenant_id)
    avi_pool_uuids = _get_avi_pool_uuids(driver, context, pool)
    avi_hm_uuid = os2avi_uuid("healthmonitor", hm.id)
    avi_hm_ref = "/api/healthmonitor/" + avi_hm_uuid
    data = {action: {'health_monitor_refs': [avi_hm_ref]}}
    for avi_pool_id in avi_pool_uuids:
        client.patch('pool', avi_pool_id, data, avi_tenant_uuid,
                     ignore_non_existent_object=(action == "delete"),
                     ignore_non_existent_tenant=(action == "delete"))


def form_vsvip_uuid(lb_id):
    return os2avi_uuid("vsvip", lb_id)


def form_vrf_context_uuid(subnet_uuid):
    return os2avi_uuid('vrfcontext', subnet_uuid)


def form_avi_vsvip_obj(os_lb, cloud, vrf_context_ref=None):
    # use loadbalancer's ip address and network paramaeters
    vip = {}
    if netaddr.IPAddress(os_lb.vip_address).version == 6:
        vip['ip6_address'] = {'type': 'V6',
                              'addr': os_lb.vip_address}
        vip['subnet6_uuid'] = os_lb.vip_subnet_id
    else:
        vip['ip_address'] = {'type': 'V4',
                             'addr': os_lb.vip_address}
        vip['subnet_uuid'] = os_lb.vip_subnet_id

    vip['port_uuid'] = os_lb.vip_port_id

    vsvip = {}
    vsvip["uuid"] = form_vsvip_uuid(os_lb.id)
    vsvip['cloud_ref'] = ("/api/cloud?name=%s" % cloud)
    if vrf_context_ref:
        vsvip['vrf_context_ref'] = vrf_context_ref

    vsvip["vip"] = [vip, ]
    return vsvip


def form_avi_vrf_context_obj(subnet_uuid, cloud):
    vrf_context = {}
    vrf_context['uuid'] = form_vrf_context_uuid(subnet_uuid)
    vrf_context['name'] = 'subnet-%s' % subnet_uuid
    vrf_context['cloud_ref'] = ("/api/cloud?name=%s" % cloud)
    vrf_context['description'] = 'auto-created'
    vrf_context['system_default'] = False
    return vrf_context


def update_vsvip(os_lb, avi_client, avi_tenant_uuid, cloud, vsvip=None,
                 vrf_context_ref=None):
    create = False
    if not vsvip:
        vsvip = form_avi_vsvip_obj(os_lb, cloud,
                                   vrf_context_ref=vrf_context_ref)
        create = True

    lb_name = os_lb.name or os_lb.vip_address
    vsvip_name = "vsvip-" + lb_name
    vsvip['name'] = vsvip_name
    vsvip['vip'][0]['enabled'] = os_lb.admin_state_up
    if create:
        res = avi_client.create("vsvip", vsvip, avi_tenant_uuid)
    else:
        res = avi_client.update("vsvip", vsvip['uuid'], vsvip, avi_tenant_uuid)

    return res


def delete_vsvip(os_lb, avi_client, contrail_lb=None):
    vsvip_uuid = None
    avi_tenant_uuid = None
    if os_lb:
        vsvip_uuid = form_vsvip_uuid(os_lb.id)
        avi_tenant_uuid = os2avi_uuid("tenant", os_lb.tenant_id)
    elif contrail_lb:
        lb_id = contrail_lb.get('id', None)
        tenant_id = contrail_lb.get('tenant_id', None)
        if lb_id and tenant_id:
            vsvip_uuid = form_vsvip_uuid(lb_id)
            avi_tenant_uuid = os2avi_uuid("tenant", tenant_id)

    if vsvip_uuid and avi_tenant_uuid:
        avi_client.delete("vsvip", vsvip_uuid, avi_tenant_uuid)


def get_vrf_context(subnet_uuid, cloud, avi_tenant_uuid, avi_client,
                    create=False):
    uuid = form_vrf_context_uuid(subnet_uuid)
    vrf_context = {}
    try:
        vrf_context = avi_client.get('vrfcontext', uuid, avi_tenant_uuid)
    except ObjectNotFound:
        pass

    if vrf_context:
        return vrf_context

    if not create:
        return {}

    vrf_context = form_avi_vrf_context_obj(subnet_uuid, cloud)
    try:
        avi_client.create('vrfcontext', vrf_context, avi_tenant_uuid)
    except Exception as e:
        if (e.rsp.status_code == 409 and
                'already exists' in e.rsp.content.lower()):
            pass
        else:
            raise e

    vrf_context = avi_client.get('vrfcontext', uuid, avi_tenant_uuid)
    return vrf_context
