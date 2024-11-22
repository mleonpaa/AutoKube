import os
import subprocess
from paramiko import SSHClient
from paramiko import AutoAddPolicy
from scp import SCPClient
from boto3 import client
import json
import time
import argparse

scriptargs = {
     "kube_dir": "C:/Users/malep/.kube",
     "tf_dir": "C:/Users/malep/terraform/Tests", 
     "private_key_path": "C:/Users/malep/Documents/AWS/test01-key.pem"
}
tfargs = {
     "region": "eu-west-3",
     "instance_type": "t4g.small"
}

ssh_username = 'ubuntu'
ec2_name = 'kservice'



def get_ec2_info(ec2_name, aws_region):
    ec2_client = client('ec2', region_name=aws_region)

    ec2_instance = ec2_client.describe_instances(
        Filters=[
            {'Name': 'instance-state-name', 'Values': ['running']},
            {'Name': 'tag:Name', 'Values': [ec2_name]}
        ]
    )

    if len(ec2_instance) == 0:
         raise Exception("Something went wrong. No resources where found.")

    return ec2_instance['Reservations'][0]['Instances'][0]
    

def ssh_connect(dns_name, username, private_key_path):
    ssh = SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(dns_name, username=username, key_filename=private_key_path)

    return ssh


def ssh_exec(ssh_obj, cmd):
    stdin, stdout, stderr = ssh_obj.exec_command(cmd)

    return({'stdin':stdin, 'stdout':stdout, 'stderr':stderr})


def serial_read(std):
    for line in std:
        print(line.strip())


def scp_put_file(ssh_obj, src_path, dest_path):

    with SCPClient(ssh_obj.get_transport()) as scp:
        scp.put(src_path, dest_path)


def scp_get_file(ssh_obj, src_path, dest_path):

    with SCPClient(ssh_obj.get_transport()) as scp:
        scp.get(src_path, dest_path)


def run_terraform_cmd(act, *args):

     cmd = ['terraform', f"-chdir={scriptargs["tf_dir"]}", act, f"-var-file={scriptargs["tf_dir"] + "/dev.json"}"]

     if act not in ('init', 'plan', 'apply', 'destroy'):
          raise ValueError("Invalid argument.")
     
     if len(args) != 0:
          cmd = cmd + list(args)

     process = subprocess.Popen(
     cmd,
     stdout=subprocess.PIPE,
     stdin=subprocess.PIPE,
     stderr=subprocess.PIPE,
     text=True,
     encoding='utf-8'
     ) 

     for line in process.stdout:
          print(line, end='') 
     
     for line in process.stderr:
          print(f"Error: {line}", end="")


def mod_json(file_path, args):
     if not (os.path.exists(file_path)):
        data = args

     else:
          with open(file_path, 'r') as file:
               data = json.load(file)
    
          data.update(args)


     with open(file_path, 'w') as file:
                json.dump(data, file)  

             

def add_args(argsdict):

     for key in argsdict.keys():
          
          if key in scriptargs.keys():
               scriptargs[key] = argsdict[key]

          elif key in tfargs.keys():
               tfargs[key] = argsdict[key]

     scriptargs["tf_vars"] = scriptargs["tf_dir"] + "/dev.tfvars"


def deploy_cluster():

     ec2 = get_ec2_info(ec2_name, tfargs["region"])
     
     with ssh_connect(ec2['PublicDnsName'], ssh_username, scriptargs["private_key_path"]) as ssh:
          
          print("Copying SSH key to Service Machine...")
          scp_put_file(ssh, scriptargs["private_key_path"], '/home/ubuntu/')
          ssh_exec(ssh, 'chmod 400 /home/ubuntu/test01-key.pem')

          print("Configuring Cluster...")
          while(ssh_exec(ssh, "stat /home/ubuntu/AutoKube/")['stdout'].channel.recv_exit_status() != 0):
               time.sleep(2)
               
          mod_json("C:/Users/malep/APaaS_repo/k8s_dinamic_vars.json", {"lb_address_pub": ec2['PublicDnsName']})
          scp_put_file(ssh, "C:/Users/malep/APaaS_repo/k8s_dinamic_vars.yaml", "/home/ubuntu/AutoKube/")
          print("Deploying Cluster...")
          serial_read(ssh_exec(ssh, 'cd /home/ubuntu/AutoKube/ && ansible-playbook k8s_deploy.yaml')['stdout'])

          print("Setting local environment...")
          scp_get_file(ssh, ".kube/config", scriptargs["kube_dir"])




parse = argparse.ArgumentParser()
parse.add_argument("-tf_dir", default=scriptargs["tf_dir"])
parse.add_argument("-kube_dir", default=scriptargs["kube_dir"])
parse.add_argument("-private_key_path", default=scriptargs["private_key_path"])
parse.add_argument("-region", default=tfargs["region"])
parse.add_argument("-instance_type", default=tfargs["instance_type"])

add_args(vars(parse.parse_args()))
mod_json(scriptargs["tf_dir"] + "/dev.json", tfargs)

if not (os.path.isdir(scriptargs["tf_dir"] + '/.terraform')):
     run_terraform_cmd('init') 
 
a = input("Would you like to check the changes that will be applied to your AWS account before applying? (yes/no)\nOnly 'yes' will be accepted to approve.\n\nEnter value: ")

if a not in ('yes', 'no'):
     raise ValueError("Invalid argument. Only yes/no is valid.")
     
if a == 'yes':
     print("Printing changes...")
     run_terraform_cmd('plan', f'-out={scriptargs["tf_dir"] + "/k8s-plan.tfplan"}')

     b = input("\nWould you like to apply this changes? (yes/no)\nOnly 'yes' will be accepted to approve.\n\nEnter value: ")

     if b not in ('yes', 'no'):
          raise ValueError("Invalid argument. Only yes/no is valid.")
     
     if b == 'yes':
          print("Applying changes...")
          run_terraform_cmd('apply', scriptargs["tf_dir"] + "/k8s-plan.tfplan")
          deploy_cluster()

     elif b == 'no':
          print("Apply cancelled.\nPlease contact with the application manager for more information.\n")
          print(f"If you know what you are doing, change the terraform's main file in {scriptargs["tf_dir"]} directory according to your needs.\nWe don't garantee the correct functionality of the application if changes are made.")

elif a == 'no':
     print("Applying changes...")
     run_terraform_cmd('apply', "-auto-approve")
     deploy_cluster()
