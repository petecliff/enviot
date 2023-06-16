# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

import random
import time
import os
import logging
import datetime
from ltr559 import LTR559
from smbus2 import SMBus
from bme280 import BME280
from azure.iot.device import IoTHubDeviceClient, Message, MethodResponse
from pyparsing import empty

logging.basicConfig(level=logging.INFO)

bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)
ltr559 = LTR559()

# Tuning factor for compensation. Decrease this number to adjust the
# temperature down, and increase to adjust up
factor = 2.25

# The device connection string to authenticate the device with your IoT hub.
# Using the Azure CLI:
# az iot hub device-identity show-connection-string --hub-name {YourIoTHubName} --device-id MyNodeDevice --output table
CONNECTION_STRING = os.getenv("IOTHUB_DEVICE_CONNECTION_STRING")

# Define the JSON message to send to IoT Hub.
MSG_TXT = '{{"timestamp": "{timestamp}", "temperature": {temperature}, "comptemperature": {comptemperature}, "humidity": {humidity}, "pressure": {pressure}, "lux": {lux}}}'
MSG_LOG = '{{"Name": {name},"Payload": {payload}}}'

INTERVAL = 60

def create_client():
    # Create an IoT Hub client

    model_id = "dtmi:cloud:peteinthe:enviroplus;1"

    client = IoTHubDeviceClient.create_from_connection_string(
                CONNECTION_STRING,
                product_info=model_id,
                websockets=True)  # used for communication over websockets (port 443)

    # *** Direct Method ***
    #
    # Define a method request handler
    def method_request_handler(method_request):
        
        print(MSG_LOG.format(name=method_request.name, payload=method_request.payload))

        if method_request.name == "SetTelemetryInterval":
            try:
                global INTERVAL
                INTERVAL = int(method_request.payload)
            except ValueError:
                response_payload = {"Response": "Invalid parameter"}
                response_status = 400
            else:
                response_payload = {"Response": "Executed direct method {}, interval updated".format(method_request.name)}
                response_status = 200
        else:
            response_payload = {"Response": "Direct method {} not defined".format(method_request.name)}
            response_status = 404

        method_response = MethodResponse.create_from_method_request(method_request, response_status, response_payload)
        client.send_method_response(method_response)

    # *** Cloud message ***
    #
    # define behavior for receiving a message
    def message_received_handler(message):
        print("the data in the message received was ")
        print(message.data)
        print("custom properties are")
        print(message.custom_properties)

    # *** Device Twin ***
    #
    # define behavior for receiving a twin patch
    # NOTE: this could be a function or a coroutine
    def twin_patch_handler(patch):
        print("the data in the desired properties patch was: {}".format(patch))
        # Update reported properties with cellular information
        print ( "Sending data as reported property..." )
        reported_patch = {"reportedValue": 42}
        client.patch_twin_reported_properties(reported_patch)
        print ( "Reported properties updated" )

    try:
        # Attach the direct method request handler
        client.on_method_request_received = method_request_handler

        # Attach the cloud message request handler
        client.on_message_received = message_received_handler

        # Attach the Device Twin Desired properties change request handler
        client.on_twin_desired_properties_patch_received = twin_patch_handler

        client.connect()

        twin = client.get_twin()
        print ( "Twin at startup is" )
        print ( twin )
    except:
        # Clean up in the event of failure
        client.shutdown()
        raise

    return client

# Get the temperature of the CPU for compensation
def get_cpu_temperature():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = f.read()
        temp = int(temp) / 1000.0
    return temp

def get_comp_temperature():
    global cpu_temps
    print(cpu_temps)
    cpu_temp = get_cpu_temperature()
    cpu_temps = cpu_temps[1:] + [cpu_temp]
    avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
    raw_temp = bme280.get_temperature()
    comp_temp = raw_temp - ((avg_cpu_temp - raw_temp) / factor)
    return comp_temp

def writeState(message):
    fpo = open("/data/state/enviro.json", "w")
    fpo.write(message)
    fpo.write("\n")
    fpo.close()

def to2DP(num):
    return "{:.2f}".format(num)

def run_telemetry(client):
    client.connect()
    ltr559.update_sensor()

    comptemp = to2DP(get_comp_temperature())
    temperature = to2DP(bme280.get_temperature())
    humidity = to2DP(bme280.get_humidity())
    pressure = to2DP(bme280.get_pressure())
    lux = to2DP(ltr559.get_lux())
    timestamp = datetime.datetime.now().isoformat()

    msg_txt_formatted = MSG_TXT.format(temperature=temperature, comptemperature=comptemp, humidity=humidity, pressure=pressure, lux=lux, timestamp=timestamp)

    writeState(msg_txt_formatted)

    message = Message(msg_txt_formatted)

    message.content_encoding = "utf-8"
    message.content_type = "application/json"

    client.send_message(message)

def main():
    global cpu_temps 
    cpu_temps = [get_cpu_temperature()] * 5
    client = create_client()
    run_telemetry(client)
    client.shutdown()

if __name__ == '__main__':
    main()
