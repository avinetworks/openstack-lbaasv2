from oslo_config import cfg

AVI_PROV = 'Avi_ADC'
DEFAULT_CLOUD = "Default-Cloud"

AVI_OPTS = [
    cfg.StrOpt('address', default='',
               help='IP address of the Avi Controller.'),
    cfg.StrOpt('user', default='admin',
               help='The management user. Default is admin.'),
    cfg.StrOpt('password', default='', secret=True,
               help='Password for management user.'),
    cfg.BoolOpt('cert_verify', default=False,
                help='Verify the validity of the certificate'
                     ' presented by the Avi Controller. Default '
                     'is False. Set it to True if Avi Controller is'
                     ' configured with a properly-signed certificate.'),
    cfg.StrOpt('cloud', default=DEFAULT_CLOUD,
               help='Name of the cloud on Avi Controller configured for this '
                    'OpenStack. Default is %s' % DEFAULT_CLOUD),
    cfg.BoolOpt('use_placement_network_for_pool', default=False,
                help='Use pool member subnet for placement network in '
                     'Avi pool. Use this option only if you have '
                     'subnets with same CIDR in same tenant.'),
    cfg.BoolOpt('vrf_context_per_subnet', default=False,
                help='Creates VRF Context per subnet. This is needed '
                     'for handling tenant networks with overlapping '
                     'address ranges. Use this option only if you have '
                     'subnets with same CIDR in same tenant.'),
]
