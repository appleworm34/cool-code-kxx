from flask import Flask, request, jsonify
from spy.spy import find_extra_channels

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello World!'

@app.route('/investigate', methods=['POST'])
def spy():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    # parse json input
    data = request.get_json()
    print("Data: ")
    print(data)
    
    
    # networks = data.get("networks")
    
    result = find_extra_channels(data)
    print("Result: ")
    print(result)
    
    return result, 200


if __name__ == '__main__':
    app.run()