# -*- coding: utf-8 -*- 
from __future__ import absolute_import
from datetime import datetime, timedelta
import logging
import sys
import random
import string
from volttron.platform.vip.agent import Agent, Core 
from volttron.platform.agent import utils
import json
import gevent

utils.setup_logging() 
_log = logging.getLogger(__name__)

class homeownerAgent(Agent): 
    #The price_hwA1 and quantity_hwA represent the price and quantity arrays for the demand curve for this agent 
    # (x and y axises for the curve)
    price_hwA1 = []
    quantity_hwA = []
    curve_file_path = "/opt/intwine/icg-data/volttron/homeownerAgent1/curve.txt"
    
    def __init__(self, config_path, **kwargs): 
        super(homeownerAgent, self).__init__(**kwargs)
        #a constant id for all events produced by this agent
        self.produced_events_id = "".join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(20))
        self.config = utils.load_config(config_path)
        self._agent_id = self.config['agentid']
        self.destination_platform = self.config['destination-platform']
        self.destination_vip = self.config.get('destination-vip')
       
    @Core.receiver("onstart") 
    def starting(self, sender, **kwargs): 
        '''Subscribes to the platform message bus 
        on the heatbeat/listeneragent topic 
        ''' 
        self.connect_to_remote_volttron_bus()
        #curve_file_path = "/opt/intwine/icg-data/volttron/homeownerAgent1/curve.txt"
        #self.extract_curves(curve_file_path)
        self.subscribe_to_buses()

    def on_heartbeat2(self, peer, sender, bus, topic, headers, message):
        '''Simply repeats the message given. Currently used for testing to make sure agent is properly subbing/pubbing to the local bus
        '''
        #_log.info('local pubsub working: %r', message)
    
    def on_heartbeat(self, peer, sender, bus, topic, headers, message):
        headers = {
                'AgentID': self._agent_id,
        }
        
        if (topic=='request for bids'):
            print("about to extract curve")
            self.extract_curves(self.curve_file_path)
            _log.info("Bidding: quantity = %r, price = %r", quantity_hwA, price_hwA1)
            curve=['price', price_hwA1,'quantity',quantity_hwA]
            self._target_platform.vip.pubsub.publish('pubsub', 'Bidding', headers=headers, message=curve)
        elif (topic=='clearing price'):
            headers.items()
            clearing_price = message[0]
            clearing_quantity = message[1]
            _log.info('Got clearing price: %r', clearing_price)
            _log.info('Got clearing quantity: %r', clearing_quantity)
            shed_status = self.compute_shedding_action(clearing_quantity)
            openadr_message = self.create_openadr_message(shed_status)
            self.vip.pubsub.publish('pubsub', 'openADRevent', headers=headers, message=openadr_message)

    def subscribe_to_buses(self):
        ''' First subscribe to the remote volttron bus and then subscribe to the local bus
        '''
        # subscribes to all topics on remote bus
        self._target_platform.vip.pubsub.subscribe('pubsub','', callback=self.on_heartbeat) 
        # subscribes to all topics on local bus. Used for testing at the moment
        self.vip.pubsub.subscribe('pubsub', '', callback=self.on_heartbeat2)
        
    def extract_curves(self, filepath):
        ''' Extracts price and quantity data from the inputted filepath and formats the data into two arrays and stores those arrays in global variables.
        '''
        file_contents = ""
        with open(filepath) as fil:
            file_contents = fil.readlines()
        fil.close()
        stripped_file_contents = [x.strip('\n') for x in file_contents]
        if (len (stripped_file_contents) != 2):
            raise ValueError("make sure agents curve file has 2 lines/rows")
        formatted_string_prices = stripped_file_contents[0].split()
        formatted_string_quantities = stripped_file_contents[1].split()
        global price_hwA1
        global quantity_hwA
        price_hwA1 = list(map(float, formatted_string_prices))
        quantity_hwA = list(map(float, formatted_string_quantities))
        _log.info("price is %r, quantity is %r", price_hwA1, quantity_hwA)

    def connect_to_remote_volttron_bus(self):
        ''' Uses destination's ip to connect to a remote volttron bus at that ip. Must be valid ip to not raise an exception.
        '''
        agent = Agent(identity=self.destination_platform, address=self.destination_vip)
        event = gevent.event.Event()
        _log.info('vip and platform %r and %r', self.destination_platform, self.destination_vip)  
        gevent.spawn(agent.core.run, event)    
        event.wait()
        self._target_platform = agent
        print(self._agent_id) 
           
    def compute_shedding_action(self, clearing_q):
        ''' Given a clearing quantity, uses this agent's demand curve's quantities to determine how much load it must shed
        '''
        status = ""
        #assuming higher quantity <-> lower price
        assert all(quantity_hwA[i] <= quantity_hwA[i+1] for i in xrange (len(quantity_hwA)-1))
        max_quantity = quantity_hwA[-1]
        min_quantity = quantity_hwA[0]
        cutoff_estimate = 0.3
        #Partition this agent's demand quantities into bounds where if the clearing quantity is in between certain bounds,
        #then shed a certain amount depending on which bounds it is between. 
        quantity_partition_interval = (max_quantity-min_quantity)*cutoff_estimate
        no_shed_bound = max_quantity - quantity_partition_interval
        small_shed_bound = no_shed_bound - quantity_partition_interval
        med_shed_bound = small_shed_bound - quantity_partition_interval
        assert med_shed_bound > min_quantity
        if (clearing_q > no_shed_bound):
            #don't shed
            status = 0
        elif (clearing_q > small_shed_bound):
            #small shed
            status = 1
        elif (clearing_q > med_shed_bound):
            #medshed
            status = 2
        else:
            assert clearing_q <= med_shed_bound
            assert clearing_q > 0
            #big shed
            status = 3
        _log.info('dontShed lower bound is %r, smallshed lower bound is %r, medshed lower bound is %r, shedding status is %r', no_shed_bound, small_shed_bound, med_shed_bound, status)
        return status
     
    def create_openadr_message(self, shed_status):
        priority = "1"
        signal_payload = str(shed_status)
        event_type = "simple_signal"
        duration = str(60)
        #current time + duration is the start time
        start_time = datetime.strftime(datetime.now()+timedelta(0,60), '%Y-%m-%d %H:%M:%S.%f')
        message = {}
        message["event_ID"] = self.produced_events_id
        message["priority"] = priority
        message["ADR_start_time"] = start_time
        message["duration"] = duration
        message["signalPayload"] = signal_payload
        message["event_type"] = event_type
        json_message = json.dumps(message)
        return json_message


def main(argv=sys.argv): 
    '''Main method called by the executable.''' 
    try: 
        utils.vip_main(homeownerAgent) 
    except Exception as e: 
            _log.exception(e)

if __name__ == '__main__': 
    # Entry point for script 
    sys.exit(main())
