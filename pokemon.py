#Pokemon class
import pandas as pd
class Pokemon(object):
    def __init__(self):
        self.df = pd.read_csv('Kanto.csv',index_col='Nat')

    def pokename(self,index):
        name = self.df['Pokemon'][index]
        return name


if __name__ == '__main__':
    p = Pokemon()
    while True:
        k = input()
        print(p.pokename(int(k)))
