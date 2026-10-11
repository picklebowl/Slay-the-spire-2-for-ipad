import json,os,sys,urllib.request
state={'pending':'pending','success':'success','failure':'failure','cancelled':'error'}[sys.argv[1]]
url=f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
body=json.dumps({'state':state,'context':'Windows iPad assistant','description':'Windows assistant build: '+state,'target_url':url}).encode()
request=urllib.request.Request(f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/statuses/{os.environ['GITHUB_SHA']}",data=body,method='POST',headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=30) as response: assert response.status==201
print(url)
