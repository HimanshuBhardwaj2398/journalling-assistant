# import ollama

# # Before running this script, make sure you have pulled a model.
# # You can do this by running the following command in your terminal:
# # ollama pull llama3

# def run_ollama_chat():
#     """
#     This function demonstrates how to use the ollama.chat function to interact with a model.
#     """
#     try:
#         response = ollama.chat(
#             model='llama3',
#             messages=[
#                 {
#                     'role': 'user',
#                     'content': 'Why is the sky blue?',
#                 },
#             ],
#         )
#         print("Response from llama3:")
#         print(response['message']['content'])
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         print("Please make sure you have pulled the 'llama3' model by running 'ollama pull llama3' in your terminal.")

# if __name__ == "__main__":
#     run_ollama_chat()
