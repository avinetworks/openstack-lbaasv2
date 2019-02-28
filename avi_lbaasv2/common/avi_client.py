import logging

from avi_lbaasv2.avi_api.avi_api import (ApiSession, ObjectNotFound,
                                         APIError, ApiResponse)


LOG = logging.getLogger(__name__)


class AviClient(object):

    def __init__(self, controller_ip, username, password, verify=False,
                 log=LOG):
        if (not controller_ip or not username or not password):
            raise Exception("Missing Avi credentials.")
        self.log = log
        self.avi_session = ApiSession.get_session(controller_ip,
                                                  username, password,
                                                  verify=verify,
                                                  api_version='18.1.2',
                                                  lazy_authentication=True,)
        return

    def delete(self, resource_type, obj_uuid, avi_tenant_uuid,
               ignore_if_not_exists=True,
               ignore_tenant_does_not_exist=True):
        self.log.debug("In AviClient Delete: %s, %s, %s", resource_type,
                       obj_uuid, avi_tenant_uuid)
        try:
            self.avi_session.delete("%s/%s" % (resource_type, obj_uuid),
                                    tenant_uuid=avi_tenant_uuid).json()
        except ObjectNotFound as e:
            self.log.exception("Object type %s uuid %s not found: %s",
                               resource_type, obj_uuid, e)
            if not ignore_if_not_exists:
                raise
        except APIError as e:
            if(ignore_tenant_does_not_exist
                    and e.rsp.status_code == 403
                    and "tenant uuid" in e.rsp.content.lower()
                    and "does not exist" in e.rsp.content.lower()):
                self.log.exception("Tenant doesn't exist %s, when deleting "
                                   "object type %s uuid %s: %s",
                                   avi_tenant_uuid, resource_type, obj_uuid, e)
            else:
                raise
        return

    def create(self, resource_type, resource_def, avi_tenant_uuid):
        self.log.debug("In AviClient Create: %s, %s, %s", resource_type,
                       resource_def, avi_tenant_uuid)
        headers = {}
        if 'uuid' in resource_def:
            headers["Slug"] = resource_def["uuid"]
        return self.avi_session.post(resource_type, data=resource_def,
                                     tenant_uuid=avi_tenant_uuid,
                                     headers=headers).json()

    def update(self, resource_type, obj_uuid, resource_def, avi_tenant_uuid):
        self.log.debug("In AviClient Update: %s, %s, %s, %s", resource_type,
                       obj_uuid, resource_def, avi_tenant_uuid)
        num_retries = 10
        while num_retries:
            try:
                prev_def = self.avi_session.get(
                    "%s/%s" % (resource_type, obj_uuid),
                    tenant_uuid=avi_tenant_uuid).json()
            except ObjectNotFound:
                return self.create(resource_type, resource_def,
                                   avi_tenant_uuid)
            prev_def.update(resource_def)  # this updates prev_def inplace
            try:
                resp = self.avi_session.put(
                    "%s/%s" % (resource_type, obj_uuid),
                    tenant_uuid=avi_tenant_uuid, data=prev_def).json()
                break
            except APIError as e:
                if type(e.rsp) == ApiResponse and e.rsp.status_code == 412:
                    # concurrent update error case; retry
                    num_retries -= 1
                    if not num_retries:
                        raise
                    self.log.warn("Will retry: %s", e)
                else:
                    raise
        return resp

    def patch(self, resource_type, obj_uuid, data, avi_tenant_uuid,
              ignore_non_existent_object=False,
              ignore_non_existent_tenant=False):
        self.log.debug("In AviClient Patch: %s, %s, %s, %s", resource_type,
                       obj_uuid, data, avi_tenant_uuid)
        res = None
        try:
            res = self.avi_session.patch("%s/%s" % (resource_type, obj_uuid),
                                         data=data,
                                         tenant_uuid=avi_tenant_uuid).json()
        except ObjectNotFound as e:
            if ignore_non_existent_object:
                self.log.exception("Object type %s uuid %s not found: %s",
                                   resource_type, obj_uuid, e)
            else:
                raise
        except APIError as e:
            if(ignore_non_existent_tenant
                    and e.rsp.status_code == 403
                    and "tenant uuid" in e.rsp.content.lower()
                    and "does not exist" in e.rsp.content.lower()):
                self.log.exception("Tenant doesn't exist %s, when patching "
                                   "object type %s uuid %s: %s",
                                   avi_tenant_uuid, resource_type, obj_uuid, e)
            else:
                raise
        return res

    def get(self, resource_type, obj_uuid, avi_tenant_uuid):
        self.log.debug("In AviClient Get: %s, %s, %s", resource_type,
                       obj_uuid, avi_tenant_uuid)
        return self.avi_session.get("%s/%s" % (resource_type, obj_uuid),
                                    tenant_uuid=avi_tenant_uuid,
                                    ).json()

    def get_by_name(self, resource_type, obj_name, avi_tenant_uuid):
        self.log.debug("In AviClient Get By Name: %s, %s, %s", resource_type,
                       obj_name, avi_tenant_uuid)
        obj = self.avi_session.get_object_by_name(
            resource_type, obj_name, tenant_uuid=avi_tenant_uuid)
        if not obj:
            raise ObjectNotFound()
        return obj
