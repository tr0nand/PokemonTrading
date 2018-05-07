import hashlib
import json
from time import time,sleep
from uuid import uuid4
import pandas as pd
from flask import Flask,jsonify,request,render_template,redirect,url_for,flash
import random
import pokemon
from blockchain import Blockchain
import requests
import ast
import sys
import threading
import pandas as pd


if len(sys.argv) ==1 :
    print("Nodetracker and port number not passed")
    exit()

if len(sys.argv) ==2 :
    print("Port number not passed")
    exit()
# Instantiate our Node
app = Flask(__name__,template_folder='templates')

node = str('http://0.0.0.0:' + sys.argv[2]+ '/node')

# Instantiate the Blockchain
blockchain = Blockchain(node)
pokedex = pd.read_csv('Kanto.csv',index_col='Nat')

def pokemonname(index):
    return pokedex['Pokemon'][index]


def regnode():
    sleep(1)
    #Let tracker know about presence of this node
    print("Node registration attempted")
    url=str('http://0.0.0.0:' + sys.argv[1]+ '/nodes')
    payload={'Node':str('http://0.0.0.0:'+ sys.argv[2]+'/node')}
    requests.post(url,data=json.dumps(payload))
    print("Node registration completed")


if(len(sys.argv)==1):
    print("Node tracker port and node port not passed")
    exit()
elif(len(sys.argv)==2):
    print("Node port not passed")
    exit()


@app.route('/',methods=['GET','POST'])
def start():
    if request.method == 'GET':
        if blockchain.user:
            return redirect(url_for('home'))
        return render_template('./home.html')
    if blockchain.user:
        return redirect(url_for('home'))
    username = request.form['user']
    if username.isspace() or not username:
        return render_template('./home.html')
    blockchain.user = username
    print("User initiated")
    return redirect(url_for('home'))


@app.route('/home')
def home():
    pokes=[]
    pokenum = blockchain.own_pokes()
    for k in pokenum:
        pokes.append({'name':pokemonname(k),'id':str(str(k)+'.png')})
    return render_template('./main.html',name=blockchain.user,pokes=pokes)

@app.route('/node',methods=['POST'])
def register_node():
    data  = ast.literal_eval((request.data).decode('utf-8'))
    print("New node received-")
    print(data['Node'])
    blockchain.nodereg(data['Node'])
    if data['New'] == 'False':
        bk = requests.get(str(data['Node']+"/chain")).json()
        while(blockchain.currentmining):
            pass
        if bk['length'] > len(blockchain.chain):
            blockchain.chain = bk['chain']
            print("Consensus chain received")
    return jsonify("Received")


@app.route('/mine', methods=['GET'])
def mine():
    #if len(blockchain.current_trade) == 0:
    #    return jsonify("No transactions to mine"),200
    blockchain.currentmining = True
    last_block = blockchain.last_block
    last_proof = last_block['proof']
    proof = blockchain.proof_of_work(last_proof)
    previous_hash = blockchain.hash(last_block)
    block = blockchain.new_block(proof,previous_hash)
    blockchain.currentmining = False
    print("Mining complete")
    payload = json.dumps({'chain':blockchain.chain,'length':len(blockchain.chain)})
    for node in blockchain.nodes:
        url = str(node+'/sync')
        requests.post(url,data=payload)
    return redirect(url_for('home'))

@app.route('/trade')
def starttrade():
    pokes=[]
    pokenum = blockchain.own_pokes()
    for k in pokenum:
        pokes.append({'name':pokemonname(k),'id':str(str(k)+'.png'),'num':k})
    return render_template('./trade.html',name=blockchain.user,pokes=pokes)

@app.route('/trade/<param>')
def choosetrain(param):
    nodes = blockchain.nodes
    response=[]
    param = int(param)
    for n in nodes:
        otherpokes = blockchain.other_pokes(n)
        for i in otherpokes:
            j = pokemonname(i)
            response.append({'name':j,'id':(str(i)+".png"),'num':i,'trainer':n})
    name = pokemonname(param)
    cur = param
    param = str(param)+'.png'
    return render_template('./tradereq.html',name=name,id=param,pokes=response,cur=cur)

@app.route('/trade/outg',methods=['GET','POST'])
def tradereq():
    if request.method == 'GET':
        treq = blockchain.tradereqs
        pokes=[]
        for p in treq:
            k={}
            i= pokemonname(p['rec'])
            j=pokemonname(p['sent'])
            k['rec'] = i
            k['sent'] = j
            k['node'] =p['node']
            k['status'] = p['status']
            pokes.append(k)
        return render_template('./tradessent.html',pokes = pokes)
    if request.method == 'POST':
        timestamp=time()
        blockchain.tradereqs.append({'node':request.form['node'],'sent':int(request.form['Sendpoke']),'rec':int(request.form['Rec']),'status':'No response yet','timestamp':timestamp})
        print(blockchain.tradereqs)
        payload={'node':blockchain.node,'sent':request.form['Sendpoke'],'rec':request.form['Rec'],'timestamp':timestamp}
        url=str(request.form['node']+'/trade/off')
        requests.post(url,data = json.dumps(payload))
        print("Offer sent")
        return redirect('/trade/outg')

@app.route('/trade/off')
def tradeoff():
    tre = blockchain.offers
    pokes=[]
    for p in tre:
        k={}
        i=pokemonname(p['sent'])
        j=pokemonname(p['rec'])
        k['sent'] = i
        k['rec'] = j
        k['node']=p['node']
        k['time']=p['timestamp']
        k['sentid']=p['sent']
        k['recid']=p['rec']
        pokes.append(k)
    return render_template('./tradeoffers.html',pokes=pokes)

@app.route('/node/trade/off',methods=['POST'])
def tradeoffrec():
    if request.method == 'POST':
        print("Offer received")
        data = ast.literal_eval((request.data).decode('utf-8'))
        print(data)
        blockchain.offers.append({'node':data['node'],'sent':int(data['sent']),'rec':int(data['rec']),'timestamp':data['timestamp']})
        print(blockchain.offers)
        return jsonify("Received offer")

@app.route('/node/sync',methods=['POST'])
def sync():
    data = ast.literal_eval((request.data).decode('utf-8'))
    print("Received new block")
    while(blockchain.currentmining):
        pass
    if data['length'] > len(blockchain.chain):
        blockchain.chain = data['chain']
        if(len(blockchain.current_trade)>0):
            for block in blockchain.chain:
                for trade in block['trade']:
                    for curr in blockchain.current_trade:
                        if curr['hash'] == trade['hash']:
                            blockchain.current_trade.remove(curr)
    return jsonify("Request complete"),200

@app.route('/node/trade',methods=['POST'])
def add_transaction():
    values = ast.literal_eval((request.data).decode('utf-8'))
    index = blockchain.new_transaction(values['trainer1'],values['trainer2'],values['sentby1'],values['sentby2'],values['time'])
    print(blockchain.current_trade)
    return jsonify(blockchain.current_trade),200

@app.route('/trade/resp',methods=['POST'])
def traderesponse():
    if request.form['submit'] == 'Accept':
        offers = blockchain.offers
        for o in offers:
            if str(o['node']) == str(request.form['node']) and (str(o['sent']) == str(request.form['Sendpoke'])) and (str(o['rec']) == str(request.form['Rec'])) and (str(o['timestamp']) == str(request.form['tim'])):
                offers.remove(o)
                print("Offer removed")
                break
        blockchain.offers = offers
        url = str(request.form['node']+'/trade/offerresp')
        payload={'node':blockchain.node,'sent':request.form['Sendpoke'],'rec':request.form['Rec'],'tim':request.form['tim'],'status':'Accepted but Unverified'}
        print(url)
        requests.post(url,data=json.dumps(payload))
        url=str(request.form['node']+'/')
        return redirect('/trade/off')
    else:
        offers = blockchain.offers
        for o in offers:
            if str(o['node']) == str(request.form['node']) and (str(o['sent']) == str(request.form['Sendpoke'])) and (str(o['rec']) == str(request.form['Rec'])) and (str(o['timestamp']) == str(request.form['tim'])):
                offers.remove(o)
                print("Offer removed")
                break
        blockchain.offers = offers
        url = str(request.form['node']+'/trade/offerresp')
        payload={'node':blockchain.node,'sent':request.form['Sendpoke'],'rec':request.form['Rec'],'tim':request.form['tim'],'status':'Cancelled'}
        print(url)
        requests.post(url,data=json.dumps(payload))
        return redirect('/trade/off')

@app.route('/node/trade/offerresp',methods=['POST'])
def offresp():
    data = ast.literal_eval((request.data).decode('utf-8'))
    treqs=blockchain.tradereqs
    for k in treqs:
        print(k)
        if str(k['node']) == str(data['node']) and str(k['timestamp']) == str(data['tim']):
            print("HSAFSAF")
            k['status']=str(data['status'])
            break
    print(treqs)
    blockchain.tradereqs=treqs
    return jsonify("Received")


@app.route('/node/trade/new', methods=['POST'])
def new_transaction():
    values = request.get_json()
    required = ['trainer1','trainer2','sentby2','sentby1']
    if not all(k in values for k in required):
        return 'Missing values',400
    values['time'] = time()
    index = blockchain.new_transaction(values['trainer1'],values['trainer2'],values['sentby1'],values['sentby2'],values['time'])
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
    port = int(sys.argv[2])
    t1 = threading.Thread(target=regnode)
    t1.start()
    app.run(host='0.0.0.0', port=port)
