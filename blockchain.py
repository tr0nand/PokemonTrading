import hashlib
import json
from time import time
from uuid import uuid4
import pandas as pd
import random
import pokemon




#Blockchain class

class Blockchain(object):
    def __init__(self,node):
        #Existing Blockchain
        self.chain=[]
        self.user = ""
        #Current trades pending
        self.current_trade = []
        self.nodes = set()
        self.node = node
        self.currentmining = False
        self.pokedex = pd.read_csv('Kanto.csv')['Rarity']
        self.rew1=[]
        self.rew2=[]
        self.rew3=[]
        self.rew4=[]
        self.rew5=[]
        i = 1
        for p in self.pokedex:
            if p == 1:
                self.rew1.append(i)
            if p == 2:
                self.rew2.append(i)
            if p == 3:
                self.rew3.append(i)
            if p == 4:
                self.rew4.append(i)
            if p == 5:
                self.rew5.append(i)
            i = i + 1
        self.rew2 = self.rew1 + self.rew2
        self.rew3 = self.rew3 + self.rew2
        self.rew4 = self.rew4 + self.rew3
        self.rew5 = self.rew5 + self.rew4

        #Create genesis block
        self.new_block(proof=0,previous_hash='0')

        self.tradereqs=[]
        self.offers = []
        
    def own_pokes(self):
        caughtpokes=[]
        print("Own pokemon referenced")
        for block in self.chain:
            if block['miner'] == self.node:
                caughtpokes.append(block['rew'])
            for trade in block['trade']:
                if trade['trainer1'] == self.node:
                    caughtpokes.append(trade['sentby2'])
                    caughtpokes.remove(trade['sentby1'])
                elif trade['trainer2'] == self.node:
                    caughtpokes.append(trade['sentby1'])
                    caughtpokes.remove(trade['sentby2'])
        print("Own pokemon received")
        return caughtpokes

    def other_pokes(self,nodel):
        caughtpokes=[]
        print("Pokemon belonging to")
        print(nodel)
        for block in self.chain:
            if block['miner'] == nodel:
                caughtpokes.append(block['rew'])
            for trade in block['trade']:
                if trade['trainer1'] == nodel:
                    caughtpokes.append(trade['sentby2'])
                    caughtpokes.remove(trade['sentby1'])
                elif trade['trainer2'] == nodel:
                    caughtpokes.append(trade['sentby1'])
                    caughtpokes.remove(trade['sentby2'])
        print("Pokemon referenced")
        return caughtpokes


    def nodereg(self,node):
        self.nodes.add(node)

    def new_block(self,proof,previous_hash = None):
        #Create a new block after mining in the blockchain
        #previous_hash = None for the genesis block
        trans = len(self.current_trade)
        block = {
        'index':len(self.chain) + 1,
        'timestamp': time(),
        'trade': self.current_trade,
        'proof': proof,
        'previous_hash': previous_hash or self.hash(self.chain[-1]),
        'miner':self.node
        }
        self.current_trade=[]
        if trans == 0:
            rew = random.choice(self.rew1)
        elif trans < 5:
            rew = random.choice(self.rew2)
        elif trans < 10:
            rew = random.choice(self.rew3)
        elif trans < 20:
            rew = random.choice(self.rew4)
        else:
            rew = random.choice(self.rew5)
        block['rew']=rew;
        self.chain.append(block)
        print("Block mined and added to chain")
        return block



    def new_transaction(self,trainer1,trainer2,sentby1,sentby2,timesent):
        #creates a new trade to go into next mined block

        ctrade={
            'trainer1': trainer1,
            'trainer2': trainer2,
            'sentby1': sentby1,
            'sentby2' : sentby2,
            'time' : timesent
        }
        hashtrans = self.hash(ctrade)
        ctrade['hash'] = hashtrans
        self.current_trade.append(ctrade)
        return self.last_block['index'] + 1

    def proof_of_work(self,last_proof):
        #Simple proof of work algorithm:

        proof = 0;
        print("Mining going on")
        lastb = self.hash(self.chain[-1])
        while self.valid_proof(last_proof,proof,lastb) is False:
            proof +=1
        print("Proofofwork found")
        return proof

    def valid_proof(self,last_proof,proof,lasthash):
        guess = str(str(last_proof+proof)+str(lasthash)).encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == '0000'



    @staticmethod
    def hash(block):
        #Creates a SHA-256 hash of a block

        block_string = json.dumps(block,sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()


    @property
    def last_block(self):
        # Returns the last Block in the chain
        return self.chain[-1]
