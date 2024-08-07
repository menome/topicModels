# -*- coding: utf-8 -*-
import time
import logging
import uuid
import os
##for rmq
import pika
##for config and node data
import json
import numpy as np

##for topic modeler
from gensim import corpora, models, similarities, parsing
##for graph database access
from neo4j.v1 import GraphDatabase, basic_auth
from neo4j.util import watch
from sys import stdout

watch("neo4j.bolt", logging.WARNING, stdout)

#Log format
LOG_FORMAT = ('%(levelname) -10s %(asctime)s %(name) -30s %(funcName) '
              '-35s %(lineno) -5d: %(message)s')
LOGGER = logging.getLogger(__name__)
##Configuration file address, for dockerized run
CONFIG_ADDRESS = "./config/config.json"

################################
######TOPIC MODELING CODE#######
################################

class TopicModeler():
    def __init__(self, config):
        #first we need to set up and parse our config file
        self.num_topic_links = int(os.environ.get("NUM_TOPIC_LINKS",config["NUM_TOPIC_LINKS"]))
        #self.corpus = corpora.MmCorpus(config["CORPUS_ADDRESS"])
        self.dictionary = corpora.Dictionary.load_from_text(os.environ.get("DICT_ADDRESS",config["DICT_ADDRESS"]))
        self.lda = models.LdaModel.load(os.environ.get("LDA_MODEL_ADDRESS",config["LDA_MODEL_ADDRESS"]))

        #loads all of the information needed to model topics
        #that is the corpus, dictionary and model

        # Load DB info. Let os environment variables override this.
        uri = os.environ.get('DB_ADDRESS',config["DB_ADDRESS"])
        user = os.environ.get('DB_USER',config["DB_USER"])
        password = os.environ.get('DB_PASS',config["DB_PASS"])

        #now we need to connect to the database instance so we can add our models to the graph
        time.sleep(5)
        self._driver = GraphDatabase.driver(uri, auth=(user,password),encrypted=True)
        #LOGGER.info('HEEEEEEEYYYYYOOOOOOOO- CONNECTED TO THE GRAPH')
        ##this statement prints out the topics and words with associated weight values
        #LOGGER.info(self.lda.show_topics(25,num_words=25,log=True,formatted=False))

    def close(self):
        LOGGER.info('CLOSING DOWN NEO4J CONNCETION')
        self._driver.close()


    def setupGraph(self):
        #this function takes the modeled topics and draws nodes for them in the graph
        topics = self.lda.show_topics(num_topics=-1, num_words=15, log=False, formatted=False)
        #also creates nodes for the words attahed to the topics and links them, creating a topic map
        session = self._driver.session()
        #if(session.read_transaction(lambda tx: tx.run("MATCH (t:Topic) RETURN COUNT(t)")) > 0):
        #    return session.close()
        #LOGGER.info("SETTING UP WTF?????")
        # session.read_transaction(lambda tx: tx.run("MATCH (t:Topic) RETURN COUNT(t)"))
        # session.write_transaction(lambda tx: tx.run("CREATE CONSTRAINT ON (a:Word) ASSERT a.Name IS UNIQUE"))
        # session.write_transaction(lambda tx: tx.run("CREATE CONSTRAINT ON (a:Topic) ASSERT a.Name IS UNIQUE"))
        #LOGGER.info("SETTING UP (2) WTF?????")
        #For every word in every topic, link the word node to the topic node
        for i,topic in enumerate(topics):
            #create a discription string
            #print(topic)
            des = ""
            for j,term in enumerate(topic[1]):
                if(j<5):
                    des += (term[0] + ", ")
                session.write_transaction(lambda tx: self.linkTopicWords(tx, str(i), term[0], term[1]))
            #LOGGER.info(des[:-1])
            session.write_transaction(lambda tx: self.addTopicDescription(tx, str(i),des[:-2]))
        return session.close()


    def addTopicDescription(self, tx, tnum, des):
       return tx.run("MATCH (t: Topic:Facet {Code: {tnum}}) SET t.Name = {des}",{"tnum":tnum,"des":des})

    def linkTopicWords(self, tx, tnum, word, weight):
        return tx.run("MERGE (t: Topic:Facet {Code: {tnum}}) ON CREATE SET t.Uuid = apoc.create.uuid() MERGE (w: Word:Facet {Name: {word}}) ON CREATE SET w.Uuid = apoc.create.uuid() MERGE (t)-[r:HAS_FACET {weight:{weight}}]->(w)",{"tnum":tnum,"word":word, "weight":float(np.float64(weight))})

    def modelDoc(self, data, channel):
        #input should be the message off the bus
        #first we need to grab the key used to grab the node from the graph
        # LOGGER.info(data)
        self.uuid = str(data["Uuid"])
        # self.prunedUri = str(data["Path"])
        LOGGER.info("starting session")
        #then we need to query the graph for the fulltext of that node
        session = self._driver.session()
        LOGGER.info("Attempting to extract fulltext from document")

        try:
            text = session.read_transaction(self.matchNode)
            LOGGER.info("Modeling Document")
            session.close()
        except Exception as e:
            LOGGER.info("Error reading fullText from graph\n" + e)
            return session.close()

        #LOGGER.info(text)

        if not text[0]:
            return 
        #Now we neeed to perform pre-processing on the fulltext from the node
        #That is to say. Lowercased and stemmed and stopworded
        doc = parsing.preprocessing.preprocess_string(text[0])
        #turn it into a vector bag of
        vec_bow = corpora.Dictionary.doc2bow(self.dictionary, doc)
        #model that shiet with that lda bitch
        doc_topics = sorted(self.lda[vec_bow],key=lambda x: x[1],reverse=True)
        #LOGGER.info("Document modeled." + str(len(doc_topics)) + " relevant topics, capping to " + str(self.num_topic_links))
        #LOGGER.info(doc_topics)
        #create the harvester message
        
        message = ({'NodeType':'File','Priority':2,'ConformedDimensions':{'Uuid':self.uuid},'Properties':{},'Connections':[]})
        #LOGGER.info(message)
        for i,topic in enumerate(doc_topics):
            #LOGGER.info('topic : ' + str(i))
            if i<self.num_topic_links:
                con = ({'Label':'Facet','NodeType':'Topic','RelType':'HAS_FACET','RelProps':{'weight':float(np.float32(topic[1]))},'ForwardRel':True,'ConformedDimensions':{'Code':str(topic[0])}})
                #LOGGER.info(con)
                message['Connections'].append(con)

        LOGGER.info("Publishing message to refinery")

        channel.basic_publish(exchange='syncevents',routing_key='syncevents.harvester.updates.topicmodeler',body=json.dumps(message))

        #want to replace this with a harvester message
        # for i,topic in enumerate(doc_topics):
        #     LOGGER.info('topic : ' + str(i))
        #     if i<self.num_topic_links:
        #         session.write_transaction(lambda tx: self.linkTopics(tx,str(topic[0]),topic[1]))
        #LOGGER.info(doc_topics)
        #now that we are done modeling the document close off this session
        return 

    def linkTopics(self, tx, tnum, weight):
        return tx.run("MATCH (t: Topic:Facet {Code: {tnum}}) WITH t MATCH (f: File {Uuid: {uuid}}) MERGE (f)-[c:HAS_FACET]->(t) ON CREATE SET c.weight = {weight}",{"tnum":tnum,"uuid":self.uuid, "weight":float(np.float32(weight))})


    def matchNode(self, tx):
        return tx.run("MATCH (f:Card {Uuid: {uuid}}) RETURN f.FullText",{"uuid":self.uuid}).single().values()

    def matchArticleNode(self, tx):
        return tx.run("MATCH (f: Article {Uuid: {uuid}}) RETURN f",{"uuid":self.uuid}).summary()

   # def stir():
        #this function is used when we want to recoup the model and reclassify documents
        #first it grabs the nodes for all topics in the graph
        #Then it grabs a list of the documents linked to the topics
        #then it replaces the topics with new ones by deleting the old ones and calling setup graph
        #then it runs the classifier on all of the documents we Unlinked, linking them into the graph


###############################
#####RMQ code##################
###############################
class RMQConsumer(object):
    """Consumer will handle unexpected interactions
    with RabbitMQ such as channel and connection closures.

    If RabbitMQ closes the connection, it will reopen it. You should
    look at the output, as there are limited reasons why the connection may
    be closed, which usually are tied to permission related issues or
    socket timeouts.

    If the channel is closed, it will indicate a problem with one of the
    commands that were issued and that should surface in the output as well.

    """
    EXCHANGE = 'fpp'
    EXCHANGE_TYPE = 'topic'
    QUEUE = 'topic_model'
    ROUTING_KEY = 'fpp.topicmodels'

    def __init__(self, config):
        """Create a new instance of the consumer class, passing in the AMQP
        URL used to connect to RabbitMQ.

        :param str amqp_url: The AMQP url to connect with

        """
        self._connection = None
        self._channel = None
        self._closing = False
        self._consumer_tag = None
        self._url = os.environ.get('CONNECTION_STRING',config["CONNECTION_STRING"])

        #Here is where we set up the modeler and stuff
        self.tm = TopicModeler(config)
        self.tm.setupGraph()

    def connect(self):
        """This method connects to RabbitMQ, returning the connection handle.
        When the connection is established, the on_connection_open method
        will be invoked by pika.

        :rtype: pika.SelectConnection

        """
        LOGGER.info('Connecting to %s', self._url)
        return pika.SelectConnection(pika.URLParameters(self._url),
                                     self.on_connection_open,
                                     stop_ioloop_on_close=False)

    def on_connection_open(self, unused_connection):
        """This method is called by pika once the connection to RabbitMQ has
        been established. It passes the handle to the connection object in
        case we need it, but in this case, we'll just mark it unused.

        :type unused_connection: pika.SelectConnection

        """
        LOGGER.info('Connection opened')
        self.add_on_connection_close_callback()
        self.open_channel()

    def add_on_connection_close_callback(self):
        """This method adds an on close callback that will be invoked by pika
        when RabbitMQ closes the connection to the publisher unexpectedly.

        """
        LOGGER.info('Adding connection close callback')
        self._connection.add_on_close_callback(self.on_connection_closed)

    def on_connection_closed(self, connection, reply_code, reply_text):
        """This method is invoked by pika when the connection to RabbitMQ is
        closed unexpectedly. Since it is unexpected, we will reconnect to
        RabbitMQ if it disconnects.

        :param pika.connection.Connection connection: The closed connection obj
        :param int reply_code: The server provided reply_code if given
        :param str reply_text: The server provided reply_text if given

        """
        self._channel = None
        if self._closing:
            self._connection.ioloop.stop()
        else:
            LOGGER.warning('Connection closed, reopening in 5 seconds: (%s) %s',
                           reply_code, reply_text)
            self._connection.add_timeout(5, self.reconnect)

    def reconnect(self):
        """Will be invoked by the IOLoop timer if the connection is
        closed. See the on_connection_closed method.

        """
        # This is the old connection IOLoop instance, stop its ioloop
        self._connection.ioloop.stop()

        if not self._closing:

            # Create a new connection
            self._connection = self.connect()

            # There is now a new connection, needs a new ioloop to run
            self._connection.ioloop.start()

    def open_channel(self):
        """Open a new channel with RabbitMQ by issuing the Channel.Open RPC
        command. When RabbitMQ responds that the channel is open, the
        on_channel_open callback will be invoked by pika.

        """
        LOGGER.info('Creating a new channel')
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_channel_open(self, channel):
        """This method is invoked by pika when the channel has been opened.
        The channel object is passed in so we can make use of it.

        Since the channel is now open, we'll declare the exchange to use.

        :param pika.channel.Channel channel: The channel object

        """
        LOGGER.info('Channel opened')
        self._channel = channel
        self.add_on_channel_close_callback()
        self.setup_exchange(self.EXCHANGE)

    def add_on_channel_close_callback(self):
        """This method tells pika to call the on_channel_closed method if
        RabbitMQ unexpectedly closes the channel.

        """
        LOGGER.info('Adding channel close callback')
        self._channel.add_on_close_callback(self.on_channel_closed)

    def on_channel_closed(self, channel, reply_code, reply_text):
        """Invoked by pika when RabbitMQ unexpectedly closes the channel.
        Channels are usually closed if you attempt to do something that
        violates the protocol, such as re-declare an exchange or queue with
        different parameters. In this case, we'll close the connection
        to shutdown the object.

        :param pika.channel.Channel: The closed channel
        :param int reply_code: The numeric reason the channel was closed
        :param str reply_text: The text reason the channel was closed

        """
        LOGGER.warning('Channel %i was closed: (%s) %s',
                       channel, reply_code, reply_text)
        self._connection.close()

    def setup_exchange(self, exchange_name):
        """Setup the exchange on RabbitMQ by invoking the Exchange.Declare RPC
        command. When it is complete, the on_exchange_declareok method will
        be invoked by pika.

        :param str|unicode exchange_name: The name of the exchange to declare

        """
        LOGGER.info('Declaring exchange %s', exchange_name)
        self._channel.exchange_declare(self.on_exchange_declareok,
                                       exchange_name,
                                       self.EXCHANGE_TYPE, durable=True)

    def on_exchange_declareok(self, unused_frame):
        """Invoked by pika when RabbitMQ has finished the Exchange.Declare RPC
        command.

        :param pika.Frame.Method unused_frame: Exchange.DeclareOk response frame

        """
        LOGGER.info('Exchange declared')
        self.setup_queue(self.QUEUE)

    def setup_queue(self, queue_name):
        """Setup the queue on RabbitMQ by invoking the Queue.Declare RPC
        command. When it is complete, the on_queue_declareok method will
        be invoked by pika.

        :param str|unicode queue_name: The name of the queue to declare.

        """
        LOGGER.info('Declaring queue %s', queue_name)
        self._channel.queue_declare(self.on_queue_declareok, queue_name, durable=False)

    def on_queue_declareok(self, method_frame):
        """Method invoked by pika when the Queue.Declare RPC call made in
        setup_queue has completed. In this method we will bind the queue
        and exchange together with the routing key by issuing the Queue.Bind
        RPC command. When this command is complete, the on_bindok method will
        be invoked by pika.

        :param pika.frame.Method method_frame: The Queue.DeclareOk frame

        """
        LOGGER.info('Binding %s to %s with %s',
                    self.EXCHANGE, self.QUEUE, self.ROUTING_KEY)
        self._channel.queue_bind(self.on_bindok, self.QUEUE,
                                 self.EXCHANGE, self.ROUTING_KEY)

    def on_bindok(self, unused_frame):
        """Invoked by pika when the Queue.Bind method has completed. At this
        point we will start consuming messages by calling start_consuming
        which will invoke the needed RPC commands to start the process.

        :param pika.frame.Method unused_frame: The Queue.BindOk response frame

        """
        LOGGER.info('Queue bound')
        self.start_consuming()

    def start_consuming(self):
        """This method sets up the consumer by first calling
        add_on_cancel_callback so that the object is notified if RabbitMQ
        cancels the consumer. It then issues the Basic.Consume RPC command
        which returns the consumer tag that is used to uniquely identify the
        consumer with RabbitMQ. We keep the value to use it when we want to
        cancel consuming. The on_message method is passed in as a callback pika
        will invoke when a message is fully received.

        """
        LOGGER.info('Issuing consumer related RPC commands')
        self.add_on_cancel_callback()
        self._consumer_tag = self._channel.basic_consume(self.on_message,
                                                         self.QUEUE)

    def add_on_cancel_callback(self):
        """Add a callback that will be invoked if RabbitMQ cancels the consumer
        for some reason. If RabbitMQ does cancel the consumer,
        on_consumer_cancelled will be invoked by pika.

        """
        LOGGER.info('Adding consumer cancellation callback')
        self._channel.add_on_cancel_callback(self.on_consumer_cancelled)

    def on_consumer_cancelled(self, method_frame):
        """Invoked by pika when RabbitMQ sends a Basic.Cancel for a consumer
        receiving messages.

        :param pika.frame.Method method_frame: The Basic.Cancel frame

        """
        LOGGER.info('Consumer was cancelled remotely, shutting down: %r',
                    method_frame)
        if self._channel:
            self._channel.close()

    def on_message(self, unused_channel, basic_deliver, properties, body):
        """Invoked by pika when a message is delivered from RabbitMQ. The
        channel is passed for your convenience. The basic_deliver object that
        is passed in carries the exchange, routing key, delivery tag and
        a redelivered flag for the message. The properties passed in is an
        instance of BasicProperties with the message properties and the body
        is the message that was sent.

        :param pika.channel.Channel unused_channel: The channel object
        :param pika.Spec.Basic.Deliver: basic_deliver method
        :param pika.Spec.BasicProperties: properties
        :param str|unicode body: The message body

        """
        #LOGGER.info('Received message # %s from %s: %s',basic_deliver.delivery_tag, properties.app_id, body)
        LOGGER.info("Received message")

        #####Here is where actual work goes!
        try:
            data = json.loads(body.encode('ascii', 'ignore'))
            LOGGER.info(data)
            # if "DELETE" not in str(data["EventType"]):
            self.tm.modelDoc(data, self._channel)
        except:
            print "TM errored on incomming message"
            self.acknowledge_message(basic_deliver.delivery_tag)
            return


        self.acknowledge_message(basic_deliver.delivery_tag)

    def acknowledge_message(self, delivery_tag):
        """Acknowledge the message delivery from RabbitMQ by sending a
        Basic.Ack RPC method for the delivery tag.

        :param int delivery_tag: The delivery tag from the Basic.Deliver frame

        """
        LOGGER.info('Acknowledging message %s', delivery_tag)
        self._channel.basic_ack(delivery_tag)

    def stop_consuming(self):
        """Tell RabbitMQ that you would like to stop consuming by sending the
        Basic.Cancel RPC command.

        """
        if self._channel:
            LOGGER.info('Sending a Basic.Cancel RPC command to RabbitMQ')
            self._channel.basic_cancel(self.on_cancelok, self._consumer_tag)

    def on_cancelok(self, unused_frame):
        """This method is invoked by pika when RabbitMQ acknowledges the
        cancellation of a consumer. At this point we will close the channel.
        This will invoke the on_channel_closed method once the channel has been
        closed, which will in-turn close the connection.

        :param pika.frame.Method unused_frame: The Basic.CancelOk frame

        """
        LOGGER.info('RabbitMQ acknowledged the cancellation of the consumer')
        self.close_channel()

    def close_channel(self):
        """Call to close the channel with RabbitMQ cleanly by issuing the
        Channel.Close RPC command.

        """
        LOGGER.info('Closing the channel')
        self._channel.close()

    def run(self):
        """Run the example consumer by connecting to RabbitMQ and then
        starting the IOLoop to block and allow the SelectConnection to operate.

        """
        self._connection = self.connect()
        self._connection.ioloop.start()

    def stop(self):
        """Cleanly shutdown the connection to RabbitMQ by stopping the consumer
        with RabbitMQ. When RabbitMQ confirms the cancellation, on_cancelok
        will be invoked by pika, which will then closing the channel and
        connection. The IOLoop is started again because this method is invoked
        when CTRL-C is pressed raising a KeyboardInterrupt exception. This
        exception stops the IOLoop which needs to be running for pika to
        communicate with RabbitMQ. All of the commands issued prior to starting
        the IOLoop will be buffered but not processed.

        """
        LOGGER.info('Stopping')
        self._closing = True
        self.stop_consuming()
        # self._connection.ioloop.start()
        LOGGER.info('Stopped')

    def close_connection(self):
        """This method closes the connection to RabbitMQ."""
        LOGGER.info('Closing connection')
        self._connection.close()




#########################
####Main server Code#####
#########################
def main():
    ###set up logger
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    ##Load in config file##
    with open(CONFIG_ADDRESS) as cfg:
        data = json.load(cfg)
        ##Create a consumer to consume RMQP##
        con = RMQConsumer(data)



    LOGGER.info("Now running consumer")
    ##Run the consumer
    try:
        con.run()
    except KeyboardInterrupt:
        con.stop()
    except Exception as ex:
        con.stop()
        raise ex


if __name__ == '__main__':
    main()
