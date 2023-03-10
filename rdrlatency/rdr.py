import argparse
import logging
import os

import yaml

from ocpnetsplit.machineconfig import (
    get_new_mc,
    create_file_dict,
    create_systemdunit_dict,
)
from ocpnetsplit.ocp import run_oc

logging.basicConfig(level=logging.INFO)


def create_latency_mc_dict(role, latency, ip_list):
    """
    Create ``MachineConfig`` dict with latency systemd units and scripts.

    Args:

        mcp (string): name of ``MachineConfig`` role (and also
            ``MachineConfigPool``) where the ``MachineConfig`` generated by
            this function should be deployed. Usually ``master`` or ``worker``.
        latency (int): zone latency created via Linux Traffic Control in ms

    Returns:
        dict: MachineConfig dict
    """
    temp = latency / 2
    latency = int(temp)
    mcd = get_new_mc(role, "network-latency")

    # include a config file to modprobe sch_netem kernel module
    file_dict = create_file_dict(
        "sch_netem.conf", "sch_netem", target_dir="/etc/modules-load.d"
    )
    mcd["spec"]["config"]["storage"]["files"].append(file_dict)

    network_latency = f"""#!/bin/bash
# Copyright 2021 Martin Bukatovič <mbukatov@redhat.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


if [[ $# = 0 ]]; then
  show_help
  exit
fi

# debug mode
if [[ $1 = "-d" ]]; then
  # shellcheck disable=SC2209
  DEBUG_MODE=echo
  shift
else
  unset DEBUG_MODE
fi

# integer with egress latency is the only argument of the script
case $1 in
  help|-h)   show_help; exit;;
  [0-9]*)    latency=$1; shift;;
  *)         show_help; exit 1
esac


# locate main network interface (assuming all nodes are on a single network)
iface=$(ip route show default | cut -d' ' -f5)

# TODO: polish this to create as few changes in traffic queues as possible,
# so that the original configuration could be restored without node reboot
$DEBUG_MODE tc qdisc del dev "${{iface}}" root
$DEBUG_MODE tc qdisc add dev "${{iface}}" root handle 1: prio
$DEBUG_MODE tc qdisc add dev "${{iface}}" parent 1:1 handle 2: netem delay "${{latency}}"ms

# create tc filter/classifier for nodes in other zones, and direct traffic
# heading to them via netem qdisc
declare -a ip_list=({ip_list})


for ip_adddr in "${{ip_list[@]}}"; do
    $DEBUG_MODE tc filter add dev "${{iface}}" parent 1: protocol ip prio 2 u32 match ip dst $ip_adddr/32 flowid 3:1
done

    """
    # include latency script file
    script_dict = create_file_dict("network-latency.sh", network_latency)
    mcd["spec"]["config"]["storage"]["files"].append(script_dict)
    mcd["spec"]["config"]["storage"]["files"][1]["mode"] = 356
    # include systemd unit service for the latency script
    unit_dict = create_systemdunit_dict("network-latency.service")
    # hardcode the given latency value into systemd service unit
    unit_dict["contents"] = unit_dict["contents"].replace("LATENCY_VALUE", str(latency))
    unit_dict["contents"] = unit_dict["contents"].replace(
        "EnvironmentFile=/etc/network-split.env", ""
    )
    mcd["spec"]["config"]["systemd"]["units"].append(unit_dict)

    return mcd


def get_ip_address(kubeconfig):
    ip_addrs = ""
    oc_cmd = ["get", "nodes", "-o", "yaml"]
    node_str, _ = run_oc(oc_cmd, kubeconfig)
    node_dict = yaml.safe_load(node_str)
    for i in node_dict["items"]:
        for addr_d in i["status"]["addresses"]:
            if addr_d["type"] not in ("ExternalIP"):
                continue
            ip_addrs += "'" + addr_d["address"] + "' "
    return ip_addrs


def generate_mc_files(ip_list, file_name, latency):
    """
    Helps in generating Machineconfig files

    Args:
        ip_list (list): list if ip's to be added as dst in tc cmd
        file_name (str): File name for generating MC yaml
        latency (int): Latency in int where it will be divide by two so we can achieve specified latency

    """
    path = os.path.join(os.getcwd(), "output")
    os.makedirs(path, exist_ok=True)
    file_path = f"{path}/{file_name}-mc.yaml"
    mc_spec = []
    for role in "master", "worker":
        mc_spec.append(create_latency_mc_dict(role, latency, ip_list))
    with open(file_path, "w") as outfile:
        yaml.dump_all(mc_spec, outfile)


def main_setup_rdr():
    """
    Simple command line interface to generate MachineConfig yaml to deploy to
    make scheduling network latency.

    Example usage::

         $ python rdr.py -hkc <path> -c1kc <path> -c2kc <path>
         $ oc create -f output/<cluster_name>-mc.yaml
         $ oc get mcp
    """
    ap = argparse.ArgumentParser(description="network latency setup helper")
    ap.add_argument(
        "-hkc",
        "--hub_kubeconfig",
        dest="hub",
        metavar="LABEL",
        required=True,
        help="Kubeconfig location for Hub Cluster",
    )
    ap.add_argument(
        "-c1kc",
        "--c1_kubeconfig",
        dest="c1",
        metavar="LABEL",
        required=True,
        help="Kubeconfig location for C1 Cluster",
    )
    ap.add_argument(
        "-c2kc",
        "--c2_kubeconfig",
        dest="c2",
        metavar="LABEL",
        required=True,
        help="Kubeconfig location for C2 Cluster",
    )
    ap.add_argument(
        "--latency",
        "-l",
        default=0,
        type=int,
        required=True,
        help="network latency in ms to be created among zones",
    )
    args = ap.parse_args()

    hub = get_ip_address(kubeconfig=args.hub)
    c1 = get_ip_address(kubeconfig=args.c1)
    c2 = get_ip_address(kubeconfig=args.c2)

    logging.info("Generating MachineConfigs for HUB ")
    generate_mc_files(c1 + c2, "hub", args.latency)

    logging.info("Generating MachineConfigs for C1 ")
    generate_mc_files(hub + c2, "c1", args.latency)

    logging.info("Generating MachineConfigs for C2 ")
    generate_mc_files(hub + c1, "c2", args.latency)
