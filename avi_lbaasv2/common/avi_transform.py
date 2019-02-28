import logging
import netaddr
import uuid
import copy
from avi_lbaasv2.avi_api.avi_api import ObjectNotFound
from avi_lbaasv2.common.avi_generic import AVI_DELIM
from avi_lbaasv2.common.avi_generic import (
    os2avi_uuid, pool_update_avi_vs_pool, get_vrf_context,
    form_vsvip_uuid, update_vsvip)

LOG = logging.getLogger(__name__)


class AviHelper(object):

    """AviHelper for translations."""
    def __init__(self, avicfg, log=LOG):
        self.avicfg = avicfg
        self.log = log

    dict_lb_method = {
        'ROUND_ROBIN': 'LB_ALGORITHM_ROUND_ROBIN',
        'LEAST_CONNECTIONS': 'LB_ALGORITHM_LEAST_CONNECTIONS',
        'SOURCE_IP': 'LB_ALGORITHM_CONSISTENT_HASH'
    }

    dict_hm_type = {
        'PING': 'HEALTH_MONITOR_PING',
        'TCP': 'HEALTH_MONITOR_TCP',
        'HTTP': 'HEALTH_MONITOR_HTTP',
        'HTTPS': 'HEALTH_MONITOR_HTTPS'
    }

    dict_persist_type = {
        'SOURCE_IP': 'PERSISTENCE_TYPE_CLIENT_IP_ADDRESS',
        'HTTP_COOKIE': 'PERSISTENCE_TYPE_HTTP_COOKIE',
        'APP_COOKIE': 'PERSISTENCE_TYPE_APP_COOKIE'
    }

    dict_persist_profile_name = {
        'SOURCE_IP': 'System-Persistence-Client-IP',
        'HTTP_COOKIE': 'System-Persistence-Http-Cookie',
    }

    dict_app_profile_name = {
        'TCP': 'System-L4-Application',
        'HTTP': 'System-HTTP',
        'HTTPS': 'System-Secure-HTTP',
        'TERMINATED_HTTPS': 'System-Secure-HTTP',
    }

    def get_app_profile_ref(self, protocol, avi_client, avi_tenant_uuid):
        avi_type = self.dict_app_profile_name[protocol]
        try:
            avi_app_prof = avi_client.get_by_name("applicationprofile",
                                                  avi_type,
                                                  avi_tenant_uuid)
        except ObjectNotFound:
            self.log.exception("App profile %s not found", avi_type)
            raise
        return avi_app_prof["url"]

    def get_appcookie_profile_name(self, name, pool_id):
        AVI_APP_COOKIE_FORMAT = 'appcookie:%s:%s'
        pname = AVI_APP_COOKIE_FORMAT % (name[:10], pool_id)
        return pname

    def get_avi_ssl_profile_ref(self, profile_name, avi_client,
                                avi_tenant_uuid):
        try:
            ssl_profile = avi_client.get_by_name("sslprofile",
                                                 profile_name,
                                                 avi_tenant_uuid)
        except ObjectNotFound:
            self.log.exception("SSL profile not found: %s", profile_name)
            raise
        return ssl_profile["url"]

    def get_avi_pool_name(self, os_pool, owner_id):
        pname = "pool"
        if os_pool.name:
            pname = os_pool.name
        return pname + AVI_DELIM + owner_id

    def fill_avi_pool_uuid_name(self, avi_pool, os_pool, owner_id):
        avi_pool["uuid"] = self.get_avi_pool_uuid(os_pool.id, owner_id)
        avi_pool["name"] = self.get_avi_pool_name(os_pool, owner_id)
        return

    def transform_os_pool_to_avi_pool(self, os_pool, avi_client, context,
                                      driver):
        """transform the OS pool into AVI pool"""
        avi_pool = dict()

        avi_pool['cloud_ref'] = ("/api/cloud?name=%s" % self.avicfg.cloud)
        avi_pool['description'] = os_pool.description
        avi_pool['enabled'] = os_pool.admin_state_up
        avi_pool['lb_algorithm'] = self.dict_lb_method[os_pool.lb_algorithm]
        subkey = 'lb_algorithm_hash'
        if avi_pool['lb_algorithm'] == 'LB_ALGORITHM_CONSISTENT_HASH':
            avi_pool[subkey] = 'LB_ALGORITHM_CONSISTENT_HASH_SOURCE_IP_ADDRESS'

        avi_tenant_uuid = os2avi_uuid("tenant", os_pool.tenant_id)

        # add ssl profile if protocol is HTTPS
        avi_pool["ssl_profile_ref"] = None
        if os_pool.protocol == "HTTPS":
            avi_pool["ssl_profile_ref"] = self.get_avi_ssl_profile_ref(
                "System-Standard", avi_client, avi_tenant_uuid)

        # add members
        avi_pool['servers'] = []
        snws = {}
        if os_pool.members:
            servers = []
            for member in os_pool.members:
                if member.provisioning_status == "PENDING_DELETE":
                    continue
                avi_svr, snw = self.transform_member(member, os_pool,
                                                     context=context,
                                                     driver=driver)
                if snw:
                    snws[snw['id']] = snw
                servers.append(avi_svr)

            avi_pool["servers"] = servers

        if self.avicfg.use_placement_network_for_pool and snws:
            plcmntnws = []
            for snw in snws.values():
                addr, mask = snw['cidr'].split('/')
                pnw = {
                    "network_ref": snw['network_id'],
                    "subnet": {
                        "ip_addr": {
                            "addr": addr,
                            "type": ('V4' if snw['ip_version'] == 4
                                     else 'V6'),
                        },
                        "mask": mask,
                    },
                }
                plcmntnws.append(pnw)

            avi_pool['placement_networks'] = plcmntnws

        if getattr(self.avicfg, 'vrf_context_per_subnet', False):
            subnet_uuid = driver.objfns.get_vip_subnet_from_listener(
                context, os_pool.listener.id)
            vrf_context = get_vrf_context(subnet_uuid, self.avicfg.cloud,
                                          avi_tenant_uuid, avi_client)
            avi_pool['vrf_ref'] = vrf_context['url']

        # add healthmonitor
        avi_pool["health_monitor_refs"] = []
        os_hm = os_pool.healthmonitor
        if (os_hm and os_hm.admin_state_up and
                os_hm.provisioning_status == "ACTIVE"):
            hm_uuid = os2avi_uuid("healthmonitor", os_hm.id)
            hm_tenant_uuid = os2avi_uuid("tenant", os_hm.tenant_id)
            try:
                hm = avi_client.get("healthmonitor", hm_uuid, hm_tenant_uuid)
            except ObjectNotFound:
                self.log.warn("Healthmonitor %s not found; creating", hm_uuid)
                hm_def = self.transform_os_hm_to_avi_hm(os_hm)
                hm = avi_client.create("healthmonitor", hm_def,
                                       hm_tenant_uuid)
            avi_pool["health_monitor_refs"] = [hm["url"]]

        # session persistence
        os_persist = os_pool.session_persistence
        avi_pool['application_persistence_profile_ref'] = None
        if os_persist:
            pkey = os_persist.type
            if pkey == 'APP_COOKIE':
                persist_profile_uuid = os2avi_uuid(
                    "applicationpersistenceprofile", os_pool.id)
                try:
                    persist_profile = avi_client.get(
                        "applicationpersistenceprofile", persist_profile_uuid,
                        avi_tenant_uuid)
                    updated_persist_profile = copy.deepcopy(persist_profile)
                    self.transform_appcookie(os_pool,
                                             updated_persist_profile)
                    if updated_persist_profile != persist_profile:
                        persist_profile = avi_client.update(
                            "applicationpersistenceprofile",
                            persist_profile_uuid,
                            updated_persist_profile,
                            avi_tenant_uuid
                        )
                except ObjectNotFound:
                    persist_profile_def = self.transform_appcookie(os_pool)
                    persist_profile_def["uuid"] = persist_profile_uuid
                    persist_profile = avi_client.create(
                        "applicationpersistenceprofile", persist_profile_def,
                        avi_tenant_uuid
                    )
                ref = persist_profile["url"]
            else:
                ref = ("/api/applicationpersistenceprofile?name=" +
                       self.dict_persist_profile_name[pkey])
            avi_pool['application_persistence_profile_ref'] = ref
        return avi_pool

    def transform_member(self, os_member, os_pool, context=None, driver=None):
        """transform the OS member into AVI server"""
        avi_svr = dict()
        avi_svr['external_uuid'] = os_member.id
        if netaddr.IPAddress(os_member.address).version == 6:
            avi_svr['ip'] = {'type': 'V6', 'addr': os_member.address}
        else:
            avi_svr['ip'] = {'type': 'V4', 'addr': os_member.address}

        avi_svr['port'] = os_member.protocol_port
        avi_svr['enabled'] = (
            os_member.admin_state_up and os_pool.admin_state_up)
        avi_svr['hostname'] = os_member.address
        if os_member.weight == 0:
            # Note: When LBaaS member weight is set to 0, OpenStack expects
            # that the member will not accept any new connections but keeps
            # serving the existing connections. By disabling the server in Avi,
            # the server will not receive any new connections, but it will wait
            # for 1 min by default before closing existing connections. To wait
            # for more time (or infinite time), user has to update the
            # graceful_disable_timeout in Avi Pool.
            avi_svr['enabled'] = False

        # Convert LBaaS member weight [0..256] to Avi Server ratio [1..20]
        avi_svr['ratio'] = (os_member.weight * 20) / 257 + 1
        snwid = getattr(os_member, "subnet_id", "")
        avi_svr['subnet_uuid'] = snwid
        avi_svr['verify_network'] = True
        snw = None
        if self.avicfg.use_placement_network_for_pool and snwid:
            snw = driver.objfns.subnet_get(context, snwid)

        return avi_svr, snw

    def _transform_hm_codes(self, os_hm_codes):
        httpx = dict()
        for code in os_hm_codes.split(','):
            if '-' in code:
                s, e = code.split('-')
                s, e = int(s), int(e)
                idx = s / 100
                httpx[idx] = 1
                idx = e / 100
                httpx[idx] = 1
            else:
                s = int(code)
                idx = s / 100
                httpx[idx] = 1
        avi_codes = list()
        for idx in httpx:
            avi_codes.append('HTTP_%dXX' % idx)
        return avi_codes

    def transform_os_hm_to_avi_hm(self, os_hm):
        avi_hm = dict()
        tmo = min(os_hm.delay, os_hm.timeout)
        delay = max(os_hm.delay, os_hm.timeout)
        if tmo == delay:
            delay += 1
        avi_hm['uuid'] = os2avi_uuid("healthmonitor", os_hm.id)
        avi_hm['send_interval'] = delay
        avi_hm['receive_timeout'] = tmo
        avi_hm['failed_checks'] = os_hm.max_retries
        # no enabled on avi
        # avi_hm['enabled'] = os_hm.admin_state_up
        avi_hm['name'] = getattr(os_hm, "name", "")
        if not avi_hm["name"]:
            avi_hm['name'] = '%s%s%s' % (os_hm.type, AVI_DELIM, os_hm.id)
        avi_hm['description'] = os_hm.id
        avi_hm['type'] = self.dict_hm_type[os_hm.type]
        if avi_hm['type'] in ['HEALTH_MONITOR_HTTP', 'HEALTH_MONITOR_HTTPS']:
            avi_http_hm = dict()
            http_method = os_hm.http_method
            if not http_method:
                http_method = "GET"
            url_path = os_hm.url_path
            if not url_path:
                url_path = "/"
            avi_http_hm['http_request'] = (
                '%s %s HTTP/1.0') % (http_method, url_path)
            avi_http_hm['http_response_code'] = self._transform_hm_codes(
                os_hm.expected_codes)
            if avi_hm['type'] == 'HEALTH_MONITOR_HTTPS':
                avi_hm['https_monitor'] = avi_http_hm
            else:
                avi_hm['http_monitor'] = avi_http_hm
        return avi_hm

    def get_avi_mixed_uuid(self, avi_res_name, os_entity_id, os_owner_id):
        newid = str(uuid.uuid5(uuid.UUID(os_entity_id), os_owner_id.encode()))
        return os2avi_uuid(avi_res_name, newid)

    def get_avi_pool_uuid(self, os_pool_id, os_owner_id):
        # idlen = len(os_pool_id)
        # newid = os_pool_id[:idlen/2] + os_owner_id[idlen/2:]
        return self.get_avi_mixed_uuid("pool", os_pool_id, os_owner_id)

    def get_avi_sni_vs_uuid(self, os_sni_ref, os_listener_id):
        return self.get_avi_mixed_uuid(
            "virtualservice",
            os_sni_ref.split("/")[-1], os_listener_id)

    def get_avi_pool(self, os_pool_id, os_owner_id, avi_client,
                     avi_tenant_uuid, driver, context):
        pool_uuid = self.get_avi_pool_uuid(os_pool_id, os_owner_id)
        try:
            avi_pool = avi_client.get("pool", pool_uuid, avi_tenant_uuid)
        except ObjectNotFound:
            self.log.warn("Pool %s not found; creating", pool_uuid)
            db_pool = driver.objfns.pool_get(context, os_pool_id)
            pool_update_avi_vs_pool(driver, context, db_pool)
            avi_pool = avi_client.get("pool", pool_uuid, avi_tenant_uuid)
        return avi_pool

    def get_or_create_avi_ssl_cert(self, driver,
                                   tls_container_id, os_tenant_id,
                                   avi_client, avi_tenant_uuid):
        # check and upload the cert
        cid = tls_container_id.split("/")[-1]
        avi_kc_id = os2avi_uuid("sslkeyandcertificate", cid)
        try:
            cert = avi_client.get_by_name(
                "sslkeyandcertificate",
                avi_kc_id,
                avi_tenant_uuid)
        except ObjectNotFound:
            self.log.info("Cert not found on Avi; uploading")
            os_cert = driver.objfns.cert_get(os_tenant_id, tls_container_id)
            ssl_kc_obj = {
                # 'uuid': avi_kc_id,
                'name': avi_kc_id,
                'key': os_cert.get_private_key(),
                'certificate': {'certificate': os_cert.get_certificate()},
                'key_passphrase': os_cert.get_private_key_passphrase(),
                'intermediates': os_cert.get_intermediates(),
            }
            cert = avi_client.create(
                'sslkeyandcertificate',
                ssl_kc_obj,
                avi_tenant_uuid)
        return cert

    def transform_os_listener_to_avi_vs(self, context, os_listener, driver):
        """
        One Avi VS per LBaaSv2 listener
        :param avi_client:
        :param os_listener:
        :param avi_vs:
        :return:
        """
        avi_client = driver.client
        avi_vs = dict()
        os_loadbalancer = os_listener.loadbalancer
        lb_name = os_loadbalancer.name
        if not lb_name:
            lb_name = os_loadbalancer.vip_address
        listener_name = os_listener.name
        if not listener_name:
            listener_name = str(os_listener.protocol_port)
        avi_tenant_uuid = os2avi_uuid("tenant", os_listener.tenant_id)
        avi_vs["name"] = "%s:%s" % (lb_name, listener_name)
        avi_vs['description'] = "%s\n%s" % (os_loadbalancer.description,
                                            os_listener.description)
        avi_vs['cloud_ref'] = ("/api/cloud?name=%s" % self.avicfg.cloud)
        se_group_ref = None
        vrf_context_ref = None
        if getattr(self.avicfg, 'vrf_context_per_subnet', False):
            subnet_uuid = driver.objfns.get_vip_subnet_from_listener(
                context, os_listener.id)
            vrf_context = get_vrf_context(subnet_uuid, self.avicfg.cloud,
                                          avi_tenant_uuid, avi_client,
                                          create=False)
            if vrf_context:
                vrf_context_ref = vrf_context['url']

            # Expect one-arm mode only when VRF Context per subnet
            avi_vs['ign_pool_net_reach'] = True

        flvid = getattr(os_loadbalancer, 'flavor_id', None)
        if flvid:
            metainfo = driver.objfns.get_metainfo_from_flavor(
                context, flvid)
            if metainfo:
                se_group_ref = metainfo.get('se_group_ref', None)
                vrf_context_ref = metainfo.get('vrf_context_ref', None)

        if se_group_ref:
            avi_vs['se_group_ref'] = se_group_ref

        if vrf_context_ref:
            avi_vs['vrf_context_ref'] = vrf_context_ref

        # use listener's uuid
        avi_uuid = os2avi_uuid("virtualservice", os_listener.id)
        avi_vs["uuid"] = avi_uuid

        # enable it only if listener is up
        avi_vs['enabled'] = os_listener.admin_state_up
        vsvip = self.get_avi_vsvip(os_loadbalancer, avi_client,
                                   avi_tenant_uuid,
                                   vrf_context_ref=vrf_context_ref)
        avi_vs["vsvip_ref"] = vsvip["url"]

        # add service
        avi_service = dict()
        avi_service["port"] = os_listener.protocol_port
        # could be either PROTOCOL_HTTPS or PROTOCOL_TERMINATED_HTTPS
        avi_service["enable_ssl"] = os_listener.protocol.endswith("HTTPS")
        avi_vs["services"] = [avi_service]

        # set application_profile
        avi_vs["application_profile_ref"] = self.get_app_profile_ref(
            os_listener.protocol, avi_client, avi_tenant_uuid)

        # add default pool
        avi_vs["pool_ref"] = None
        if(os_listener.default_pool and
           os_listener.default_pool.provisioning_status != "PENDING_DELETE"):
            os_pool = os_listener.default_pool
            avi_pool = self.get_avi_pool(os_pool.id, os_listener.id,
                                         avi_client, avi_tenant_uuid, driver,
                                         context)
            avi_vs["pool_ref"] = avi_pool["url"]

        # add tls cert
        avi_vs["ssl_key_and_certificate_refs"] = []
        if os_listener.default_tls_container_id:
            cert = self.get_or_create_avi_ssl_cert(
                driver,
                os_listener.default_tls_container_id,
                os_listener.tenant_id,
                avi_client, avi_tenant_uuid)
            avi_vs["ssl_key_and_certificate_refs"] = [cert["url"]]

        # if SNI containers are present
        avi_vs["child_vses"] = []
        if os_listener.sni_containers:
            for sni in os_listener.sni_containers:
                child_vs = self.get_or_create_avi_ssl_cert(
                    driver,
                    sni.tls_container_id,
                    os_listener.tenant_id,
                    avi_client, avi_tenant_uuid)
                child_vs["uuid"] = self.get_avi_sni_vs_uuid(
                    sni.tls_container_id, os_listener.id)
                child_vs["pool_ref"] = None
                if avi_vs["pool_ref"]:
                    owner_id = child_vs["uuid"][15:]
                    child_vs["pool_ref"] = self.get_avi_pool(
                        os_pool.id, owner_id,
                        avi_client, avi_tenant_uuid, driver, context)["url"]
                avi_vs["child_vses"].append(child_vs)

        # connection limit
        connection_limit = 0
        if os_listener.connection_limit > 0:
            connection_limit = os_listener.connection_limit
        perf_lt = {"max_concurrent_connections": connection_limit}
        avi_vs["performance_limits"] = perf_lt

        return avi_vs

    def transform_appcookie(self, os_pool, avi_persist=None):
        if not avi_persist:
            avi_persist = dict()
        os_persist = os_pool.session_persistence
        pkey = os_persist.type
        ptype = self.dict_persist_type[pkey]
        pname = self.get_appcookie_profile_name(os_persist.cookie_name,
                                                os_pool.id)
        avi_persist['name'] = pname
        avi_persist['description'] = 'Openstack profile via LBaaS'
        avi_persist['persistence_type'] = ptype
        appck_profile = avi_persist.get(
            'app_cookie_persistence_profile', dict())
        appck_profile['prst_hdr_name'] = os_persist.cookie_name
        avi_persist['app_cookie_persistence_profile'] = appck_profile
        return avi_persist

    def get_avi_vsvip(self, os_lb, avi_client, avi_tenant_uuid,
                      vrf_context_ref=None):
        vsvip_uuid = form_vsvip_uuid(os_lb.id)
        try:
            vsvip = avi_client.get("vsvip", vsvip_uuid, avi_tenant_uuid)
        except ObjectNotFound:
            self.log.warn("VsVip %s not found; creating", vsvip_uuid)
            update_vsvip(os_lb, avi_client, avi_tenant_uuid, self.avicfg.cloud,
                         vrf_context_ref=vrf_context_ref)
            vsvip = avi_client.get("vsvip", vsvip_uuid, avi_tenant_uuid)

        return vsvip
