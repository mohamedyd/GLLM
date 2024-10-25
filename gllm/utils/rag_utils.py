"""
Description of this file:

This file contains functions to setup Langchain with a RAG model which uses PDF files as external knowledge source. 
The functions are used in a Streamlit application to generate G-codes for CNC machines. 
The application takes a natural language instruction as input and generates a G-code based on the instruction. 
The G-code is then validated and can be downloaded or visualized as a 3D plot.

The functions are written in Python and use the Langchain library for the LLM pipelines.

Authors: Mohamed Abdelaal, Samuel Lokadjaja

This work was done at Software AG, Darmstadt, Germany in 2023-2024 and is published under the Apache License 2.0.
"""

import openai
from langchain import hub
from PyPDF2 import PdfReader
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain


def load_pdfs(pdf_files):
    text_elements = []
    for pdf_file in pdf_files:
        pdf_reader = PdfReader(pdf_file)
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text_elements.append(page.extract_text())
    return text_elements

def setup_langchain_with_rag(pdf_files, model):
    text_elements = load_pdfs(pdf_files)
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002",openai_api_key=openai.api_key)
    vector_store = FAISS.from_texts(text_elements, embeddings)
    retrieval_qa_chat_prompt = hub.pull("langchain-ai/retrieval-qa-chat")
    combine_docs_chain = create_stuff_documents_chain(model, retrieval_qa_chat_prompt)
    retrieval_qa_chain = create_retrieval_chain(retriever=vector_store.as_retriever(),combine_docs_chain=combine_docs_chain)
    return retrieval_qa_chain