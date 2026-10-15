"""VPS su Aruba Cloud.

Usa il provider Terraform ufficiale `arubacloud/arubacloud` tramite il bridge
"Any Terraform Provider" di Pulumi (non esiste un provider Pulumi nativo).
L'SDK `pulumi_arubacloud` viene generato in locale da `pulumi package add`.

Le credenziali del provider arrivano dalle variabili d'ambiente
ARUBACLOUD_CLIENT_ID / ARUBACLOUD_CLIENT_SECRET.
"""

import pulumi
import pulumi_arubacloud as aruba

cfg = pulumi.Config()
stack = pulumi.get_stack()

location = cfg.get("location") or "ITBG-Bergamo"
zone = cfg.get("zone") or "ITBG-1"
flavor = cfg.get("flavor") or "CSO4A8"  # 4 vCPU / 8 GB
image = cfg.get("image") or "LU22-001"  # Ubuntu 22.04
disk_gb = cfg.get_int("diskSizeGb") or 50
ssh_public_key = cfg.require("sshPublicKey")
ssh_allowed_cidr = cfg.get("sshAllowedCidr") or "0.0.0.0/0"

name = f"vps-{stack}"
tags = ["vpsaruba", stack]
common = {"location": location, "tags": tags}

project = aruba.Project(
    "project",
    name=name,
    description=f"VPS {stack} gestito da Pulumi",
    tags=tags,
)

keypair = aruba.Keypair(
    "keypair",
    name=f"{name}-key",
    project_id=project.id,
    value=ssh_public_key,
    **common,
)

vpc = aruba.Vpc("vpc", name=f"{name}-vpc", project_id=project.id, **common)

subnet = aruba.Subnet(
    "subnet",
    name=f"{name}-subnet",
    project_id=project.id,
    vpc_id=vpc.id,
    type="Advanced",  # richiesto per il DHCP
    network={
        "address": "10.0.0.0/24",
        "dhcp": {
            "enabled": True,
            "range": {"start": "10.0.0.10", "count": 200},
            "routes": [{"address": "0.0.0.0/0", "gateway": "10.0.0.1"}],
            "dns": ["1.1.1.1", "8.8.8.8"],
        },
    },
    **common,
)

security_group = aruba.Securitygroup(
    "security-group",
    name=f"{name}-sg",
    project_id=project.id,
    vpc_id=vpc.id,
    **common,
)

# Le regole vengono create in sequenza per non far competere le chiamate API
# sullo stesso security group.
_rules = [
    ("ssh", "Ingress", "TCP", "22", ssh_allowed_cidr),
    ("http", "Ingress", "TCP", "80", "0.0.0.0/0"),
    ("https", "Ingress", "TCP", "443", "0.0.0.0/0"),
    ("egress-all", "Egress", "ANY", "*", "0.0.0.0/0"),
]
previous = None
rules = []
for rule_id, direction, protocol, port, cidr in _rules:
    previous = aruba.Securityrule(
        f"rule-{rule_id}",
        name=f"{name}-{rule_id}",
        project_id=project.id,
        vpc_id=vpc.id,
        security_group_id=security_group.id,
        properties={
            "direction": direction,
            "protocol": protocol,
            "port": port,
            "target": {"kind": "Ip", "value": cidr},
        },
        opts=pulumi.ResourceOptions(depends_on=[previous] if previous else []),
        **common,
    )
    rules.append(previous)

elastic_ip = aruba.Elasticip(
    "elastic-ip",
    name=f"{name}-ip",
    project_id=project.id,
    billing_period="Hour",
    **common,
)

boot_disk = aruba.Blockstorage(
    "boot-disk",
    name=f"{name}-boot",
    project_id=project.id,
    zone=zone,  # deve coincidere con la zona del server
    size_gb=disk_gb,
    billing_period="Hour",
    type="Performance",
    bootable=True,
    image=image,
    **common,
)

server = aruba.Cloudserver(
    "server",
    name=name,
    project_id=project.id,
    zone=zone,
    network={
        "vpc_uri_ref": vpc.uri,
        "subnet_uri_refs": [subnet.uri],
        "securitygroup_uri_refs": [security_group.uri],
        "elastic_ip_uri_ref": elastic_ip.uri,
    },
    settings={
        "flavor_name": flavor,
        "key_pair_uri_ref": keypair.uri,
    },
    storage={"boot_volume_uri_ref": boot_disk.uri},
    opts=pulumi.ResourceOptions(depends_on=rules),
    **common,
)

pulumi.export("serverId", server.id)
pulumi.export("publicIp", elastic_ip.address)
pulumi.export("privateIp", server.private_ip)
