import json
from time import sleep
import requests
from flask import Flask,jsonify,request,render_template,redirect
import ast
import sys
app = Flask(__name__)

nodes=set()

if len(sys.argv)!=2:
    print("Port number not passed")
    exit()
@app.route('/nodes',methods=['POST'])
def register_node():
    data  = ast.literal_eval((request.data).decode('utf-8'))
    data = data['Node']
    print(data)
    for node in nodes:
        requests.post(node,json.dumps({'Node':data,'New':'True'}))
        requests.post(data,json.dumps({'Node':node,'New':'False'}))
    nodes.add(data)
    return jsonify("Received")



if __name__ == '__main__':
    port = int(sys.argv[1])
    app.run(host='0.0.0.0', port=port)
