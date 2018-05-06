import hashlib
import json
from time import time,sleep
import threading
from uuid import uuid4
import pandas as pd
from flask import Flask,jsonify,request,render_template,redirect
import random
import pokemon
from blockchain import Blockchain
import requests
import ast
from flask_script import Manager,Server

# Instantiate our Node
app = Flask(__name__,template_folder='templates')

# Generate a globally unique address for this node
node_identifier = str(uuid4()).replace('-', '')

# Instantiate the Blockchain
blockchain = Blockchain()

#Let the Tracker know of the presence of this node
def regnode():
    sleep(1)
    print("Node registration attempted")
    url=str('http://0.0.0.0:2000/nodes')
    payload={'Node':'http://0.0.0.0:5679/node'}
    requests.post(url,data=json.dumps(payload))


#Registering the presence of other nodes
@app.route('/node',methods=['POST'])
def register_node():
    data  = ast.literal_eval((request.data).decode('utf-8'))
    print(data['Node'])
    blockchain.nodereg(data['Node'])
    if data['New'] == 'False':
        bk = requests.get(str(data['Node']+"/chain")).json()
        if bk['length'] > len(blockchain.chain):
            blockchain.chain = bk['chain']
    return jsonify("Received")


@app.route('/mine', methods=['GET'])
def mine():
    last_block = blockchain.last_block
    last_proof = last_block['proof']
    blockchain.currentmining = True
    proof = blockchain.proof_of_work(last_proof)

    previous_hash = blockchain.hash(last_block)
    block = blockchain.new_block(proof,previous_hash)
    blockchain.currentmining = False
    print("Mining complete")
    payload = json.dumps({'chain':blockchain.chain,'length':len(blockchain.chain)})
    for node in blockchain.nodes:
        url = str(node+'/sync')
        requests.post(url,data=payload)
    return jsonify("Mining complete"),200


@app.route('/node/sync',methods=['POST'])
def sync():
    data = ast.literal_eval((request.data).decode('utf-8'))
    print("Received new block")
    while(blockchain.currentmining):
        pass
    if data['length'] > len(blockchain.chain):
        blockchain.chain = data['chain']
    return jsonify("Request complete"),200

@app.route('/node/trade',methods=['POST'])
def add_transaction():
    values = ast.literal_eval((request.data).decode('utf-8'))
    index = blockchain.new_transaction(values['trainer1'],values['trainer2'],values['sentby1'],values['sentby2'])
    print(blockchain.current_trade)
    return jsonify(blockchain.current_trade),200

@app.route('/trade/new', methods=['POST'])
def new_transaction():
    values = request.get_json()
    required = ['trainer1','trainer2','sentby2','sentby1']
    if not all(k in values for k in required):
        return 'Missing values',400

    index = blockchain.new_transaction(values['trainer1'],values['trainer2'],values['sentby1'],values['sentby2'])
    payload = json.dumps(values)
    print(blockchain.current_trade)
    for node in blockchain.nodes:
        url = str(node+'/trade')
        requests.post(url,data=payload)
    return jsonify(blockchain.current_trade),200

@app.route('/node/chain', methods=['GET'])
def full_chain():
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200

if __name__ == '__main__':
    t1 = threading.Thread(target=regnode)
    t1.start()
    app.run(host='0.0.0.0', port=5679)
