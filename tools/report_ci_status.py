"""Publish the run link as a commit status so clients can find push builds."""
import json
import os
import sys
import urllib.request

states={'pending':'pending','success':'success','failure':'failure','cancelled':'error'}
state=states[sys.argv[1]]
server=os.environ['GITHUB_SERVER_URL']
repository=os.environ['GITHUB_REPOSITORY']
run_url=f"{server}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
body=json.dumps({'state':state,'context':'iPad native build',
                 'description':f'iPad NativeAOT build: {state}',
                 'target_url':run_url}).encode()
request=urllib.request.Request(
    f"{os.environ['GITHUB_API_URL']}/repos/{repository}/statuses/{os.environ['GITHUB_SHA']}",
    data=body,method='POST',
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
             'Accept':'application/vnd.github+json','Content-Type':'application/json',
             'X-GitHub-Api-Version':'2022-11-28'})
with urllib.request.urlopen(request,timeout=30) as response:
    assert response.status==201
print(f'Published {state} build status: {run_url}')
