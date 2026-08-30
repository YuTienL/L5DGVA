#!/usr/bin/env python3
import argparse,json,pathlib

ap=argparse.ArgumentParser()
ap.add_argument('--protocol',required=True)
ap.add_argument('--role',required=True)
ap.add_argument('--dut-top',required=True)
ap.add_argument('--dut-extract',required=True)
ap.add_argument('--vip-extract')
ap.add_argument('--out',required=True)
a=ap.parse_args()

dut=json.loads(pathlib.Path(a.dut_extract).read_text())
vip=json.loads(pathlib.Path(a.vip_extract).read_text()) if a.vip_extract else {}
ports=dut.get('ports',[])
packages=vip.get('packages',[])
classes=vip.get('classes',[])
package_names=[]
for x in packages:
    n=x.get('package') if isinstance(x,dict) else str(x)
    if n and n not in package_names: package_names.append(n)
class_names=[]
for x in classes:
    n=x.get('class') if isinstance(x,dict) else str(x)
    if n and n not in class_names: class_names.append(n)
agent_type=next((x for x in class_names if 'agent' in x.lower()), None)
clk=next((x.get('name') for x in ports if 'clk' in x.get('name','').lower()), 'clk')
rst=next((x.get('name') for x in ports if 'rst' in x.get('name','').lower() or 'reset' in x.get('name','').lower()), 'rst_n')

binding_status='CANDIDATE_BINDING_FROM_CURRENT_VIP_EVIDENCE' if package_names or agent_type else 'REQUIRES_EVIDENCE_SYNTHESIS'
m={
 'protocol':a.protocol,
 'role':a.role,
 'dut_top':a.dut_top,
 'interfaces':[{'name':'AUTO_DISCOVER','evidence':ports}],
 'clocks':[{'name':clk}],
 'resets':[{'name':rst}],
 'registers':[],
 'transactions':[],
 'vip':{
    'candidate_packages':packages,
    'candidate_classes':classes,
    'package_imports':package_names[:1],
    'agent_type':agent_type or 'uvm_agent',
    'agent_instance':'vip_agent',
    'binding_status':binding_status
 },
 'vip_binding':{
    'candidate_packages':packages,
    'candidate_classes':classes,
    'package_imports':package_names[:1],
    'agent_type':agent_type or 'uvm_agent',
    'agent_instance':'vip_agent',
    'binding_status':binding_status
 },
 'scoreboard_rules':[],
 'coverage_points':[],
 'smoke_tests':[{'name':'smoke'}],
 'metadata':{
    'dut_parameters':dut.get('parameters',[]),
    'state':'SEMANTIC_MODEL_DRAFT',
    'truth':'Candidate VIP binding must still be confirmed by evidence synthesis before production qualification.'
 }
}
pathlib.Path(a.out).write_text(json.dumps(m,indent=2))
print(a.out)
