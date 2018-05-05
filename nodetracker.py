import json
from time import sleep
import requests
from flask import Flask,jsonify,request,render_template,redirect
import ast
app = Flask(__name__)

nodes=set()


@app.route('/nodes',methods=['POST'])
def register_node():
    data  = ast.literal_eval((request.data).decode('utf-8'))['Node']
    print(data)

    for node in nodes:
        requests.post(node,json.dumps({'Node':data}))

    try:
        return jsonify("Received")
    finally:
        sleep(1)
        for node in nodes:
            requests.post(data,json.dumps({'Node':data}))
        nodes.add(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2000)