# -*- coding: utf-8 -*-

import logging
import json
from gensim import corpora, models, similarities
import nltk
import stop_words
from stop_words import get_stop_words
from nltk.tokenize import RegexpTokenizer
from nltk.stem.porter import PorterStemmer
from neo4j.v1 import GraphDatabase, basic_auth

LOG_FORMAT = ('%(levelname) -10s %(asctime)s %(name) -30s %(funcName) '
              '-35s %(lineno) -5d: %(message)s')
LOGGER = logging.getLogger(__name__)


class TopicModeler():


    #class variables 
    CONFIG_ADDRESS = "/config/model.json"

    def __init__(self, uri, user, password):
        #first we need to set up and parse our config file
        with open(CONFIG_ADDRESS) as cfg:
            data = json.load(cfg)
            self.corpus = corpora.MmCorpus(data["CORPUS_ADDRESS"])
            self.dictionary = corpora.Dictionary.load_from_text(data["DICT_ADDRESS"])
            self.lda = models.LdaModel.load(data["LDA_MODEL_ADDRESS"])
            self.numTopics = data["numTopics"]
        #loads all of the information needed to model topics
        #that is the corpus, dictionary and model
        #self.corpus = corpora.MmCorpus(TopicModeler.CORPUS_ADDRESS)
        #self.dictionary = corpora.Dictionary.load_from_text(TopicModeler.DICT_ADDRESS)
        #self.lda = models.LdaModel.load(TopicModeler.LDA_MODEL_ADDRESS)

        #now we need to connect to the database instance so we can add our models to the graph
        self._driver = GraphDatabase.driver(uri, auth_basic=(user,password))


    def close(self):
        self._driver.close()


    def setupGraph(self):
        #this function takes the modeled topics and draws nodes for them in the graph
        topics = self.lda.show_topics(TopicModeler.NUM_TOPICS, num_words=15, log=False, formatted=False)
        #also creates nodes for the words attahed to the topics and links them, creating a topic map
        session = self._driver.session()
        i = 0
        for topic in topics:
            #Here we have each topic, we should make nodes for them
            tNode = session.write_transaction(lambda tx: self.createTopicNode(tx, topic))
            j = 0
            for term in topic[1]:
                #Here we have each word, we should search to see if we already mapped this word
                wNode =  self.getWordNode(term)
                #Here is where we need to draw links from words to topics
                
                j = j + 1

            i = i + 1
    

    #create topic function
    #adds a new node to the graph for the topic number
    def createTopicNode(self, tx, topic):
        LOGGER.info("Topic#" + str(topic[0]))
        return tx.run("CREATE (a: Topic {topicNum: {topicNum}}) RETURN a",{"topicNum":topic[0]})
    
    #get word node function
    #polls the database for a word node, if it is not found it creates one and returns it
    def getWordNode(self, word):
        #try to poll the node from the graph and return it
        node = session.read_transaction(lambda tx: self.pollWordNode(tx, word))
        if node == None: 
           node = session.write_transaction(lambda tx: self.createWordNode(tx, word))
        #if it does not exist we create a new one
        return node
    
    #poll for word node function, polls database matching on word
    def pollWordNode(self, tx, word):
        return tx.run("MATCH (a: Word {word: {word}}) RETURN a WHERE a.word = word", {"word": word})

    #create word function, creates a new node for the word
    def createWordNode(self, tx, word):
        return tx.run("CREATE (a: Topic {topicNum: {topicNum}}) RETURN a", {"word":word})
        

    #def modelDoc(msg):
        #input should be the message off the bus
        #first we need to grab the node from the graph
        #then we pull the text from the node
        #then we run it through the LDA model
        #then we are given weights and links that we draw from the document to the topic(s)
        


   # def stir():
        #this function is used when we want to recoup the model and reclassify documents
        #first it grabs the nodes for all topics in the graph
        #Then it grabs a list of the documents linked to the topics
        #then it replaces the topics with new ones by deleting the old ones and calling setup graph
        #then it runs the classifier on all of the documents we Unlinked, linking them into the graph




    #main function (probably not used)
def main():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    
    #I now have nicely formatted corpus, dictionary, and  lda models.
    #need a high fidelity generated lda model, probs run at lunch
    #need to make functions for rabbit app to use
    #Those will be:
    # __init__ that loads all the models
    # update   updates the saved version of the corpus and models
    # terminate, kills things cleanly
    #hook up ampq to grab text from nodes in graph
    #run modeling on it
    #draw weighted links to topics in graph
    #functionality to deal with topics in graph
    
    
    
    tm.setupGraph()

    
    #LOGGER.info(tm.corpus)
   # LOGGER.info(tm.dictionary)
    #LOGGER.info(tm.lda)
    
if __name__ == '__main__':
    main()