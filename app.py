from flask import Flask, request, jsonify
from spy.spy import find_extra_channels
from mouse.mouse import choose_instructions
from mouse.mouse_gpt import handle_post

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


@app.route("/micro-mouse", methods=["POST"])
def micro_mouse():
    body = request.get_json(force=True)
    response = handle_post(body)
    
    return jsonify(response)

if __name__ == '__main__':
    app.run()