import hashlib
import json
from time import time
from uuid import uuid4

from flask import Flask,jsonify,request,render_template


#Blockchain class
class Blockchain(object):
    def __init__(self):
        #Existing Blockchain
        self.chain=[]
        #Current trades pending
        self.current_trade = []

        #Create genesis block
        self.new_block(proof=0,previous_hash='1')

        #List of all Users
        self.users= []

    def new_block(self,proof,previous_hash = None):
        #Create a new block after mining in the blockchain
        #previous_hash = None for the genesis block
        block = {
        'index':len(self.chain) + 1,
        'timestamp': time(),
        'trade': self.current_trade,
        'proof': proof,
        'previous_hash': previous_hash or self.hash(self.chain[-1]),
        }
        self.current_trade=[]
        self.chain.append(block)
        return block



    def new_transaction(self,trainer1,trainer2,sentby1,sentby2):
        #creates a new trade to go into next mined block
        self.current_trade.append(
        {
            'trainer1': trainer1,
            'trainer2': trainer2,
            'sentby1': sentby1,
            'sentby2' : sentby2,
        }
        )
        return self.last_block['index'] + 1

    def proof_of_work(self,last_proof):
        #Simple proof of work algorithm:

        proof = 0;
        while self.valid_proof(last_proof,proof) is False:
            proof +=1

        return proof

    def valid_proof(self,last_proof,proof):
        guess = str(last_proof+proof).encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == '0000'

    def checkuser(self,username):
        for k in self.users:
            if k['username'] == username:
                return False
        return True

    def createuser(self,username,passhash):
        self.users.append({'username':username,'passhash':passhash,'address':str(uuid4()).replace('-', '')})


    @staticmethod
    def hash(block):
        #Creates a SHA-256 hash of a block

        block_string = json.dumps(block,sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def retrievepass(self,user):
        for k in self.users:
            if k['username'] == user:
                return k['passhash']
    @property
    def last_block(self):
        # Returns the last Block in the chain
        return self.chain[-1]

# Instantiate our Node
app = Flask(__name__,template_folder='templates')

# Generate a globally unique address for this node
node_identifier = str(uuid4()).replace('-', '')

# Instantiate the Blockchain
blockchain = Blockchain()

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('./login.html')
    if request.method == 'POST':
        values = request.form
        if not values['Username']:
            message = "Trainername left blank"
            return render_template('./login.html',mess = message)
        if not values['pw']:
            message = "Password left blank"
            return render_template('./login.html',mess = message)
        if values['type'] == 'Log':
            if not blockchain.checkuser(values['Username']):
                ph = blockchain.retrievepass(values['Username'])
                passhash = hashlib.sha256(str(values['pw']).encode()).hexdigest()
                if ph == passhash:
                    return jsonify("Logged in")
                message = 'Invalid Password'
                return render_template('./login.html',mess = message)
            message = "Trainer doesn't exist"
            return render_template('./login.html',mess = message)
        if values['type'] == 'Reg':
            if blockchain.checkuser(values['Username']):
                passhash = hashlib.sha256(str(values['pw']).encode()).hexdigest()
                blockchain.createuser(values['Username'],passhash)
                return jsonify("New register")
            message = 'Trainername already taken. Choose a different one'
            return render_template('./login.html',mess = message)


@app.route('/mine', methods=['GET'])
def mine():
    last_block = blockchain.last_block
    last_proof = last_block['proof']
    proof = blockchain.proof_of_work(last_proof)

    #RATTATA / CATTERPIE / SHIT Reward

    previous_hash = blockchain.hash(last_block)
    block = blockchain.new_block(proof,previous_hash)


@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.get_json()
    required = ['trainer1','trainer2','sentby2','sentby1']
    if not all(k in values for k in required):
        return 'Missing values',400

    index = blockchain.new_transaction(values['trainer1'],values['trainer2'],values['sentby1'],values['sentby2'])


@app.route('/chain', methods=['GET'])
def full_chain():
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
