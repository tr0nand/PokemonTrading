# PokemonTrading
A blockchain based Pokemon Trading game

## Basis:
Want to be the ultimate Pokemon master like Red and capture all 151 Pokemon (Gen-1). Scared that Team Rocket might steal your Pokemon away? Utilizing a distributed ledger like Blockchain for this game ensures that all Pokemon rewards are accounted for, and you can't loose your Pokemon no matter what. Capture and trade Pokemon cause you Gotta Catch 'Em All .

## Requirements
This game is a python based game and all the requirements are present in the requirements.txt file.

Make sure the version of Python being used is 3.x  

Type the following command in the terminal to obtain all the required dependencies.
>pip install -r requirements.txt  

## How to play the game
Navigate to the main directory and type  
>python nodetracker.py [nodeportno]  

Where nodeportno is the port on the localhost server on which the nodetracker runs

For each individual node/trainer taking part in the game type

>python app.py [nodeportno] [trainerportno]

Where nodeportno is the same as before and trainerportno is the port on which the trainer node runs.

Go to your browser visit localhost:trainerportno to start the game  

You can start as many instances of nodes at a time to simulate different trainers

## Game Specifics

The game utilizes a distributed ledger in the form of a blockchain to keep track of all trades between trainers as well as Pokemon captured. A Pokemon can be captured by mining a block on the blockchain as the reward. Mining blocks which carry more number of transactions can result in capturing a rarer Pokemon. Once captured, these pokemon can then be traded with other trainers and they are verified once the block is mined. The incentive for miners to mine transactions are the possibilities of obtaining rarer Pokemon.

## Blockchain Specifics
The blockchain utilized has a very simple consensus algorithm to ensure agreement between miners. Every node/trainer has mining capability and the current longest chain is considered to be the correct chain. With a large number of traders this helps rule out a 51% chain attack.

The mining algorithm utilizes a simple proof of work algorithm where the SHA256 hash of two values are calculated untill the last 4 digits are found to be 0. The complexity of this can be increased by increasing the number of digits set to 0.
