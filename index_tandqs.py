import time
import sys
import os

from lib.ai import ai

# import database methods
from lib.database import featurebase_query, create_database
from lib.util import embeddings

# create the databases
databases = []
databases.append({"name": "doc_questions", "schema": "(_id string, filename string, title string, question string, keyterms stringset, page_id string, question_embedding vector(768));"})
databases.append({"name": "doc_keyterms", "schema": "(_id string, filenames stringset, titles stringset, uuids stringset, page_ids stringset);"})
for database in databases:
	create_database(database.get('name'), database.get('schema'))

# select the file
from lib.util import get_pdf_filename
filename = get_pdf_filename()
if filename:
    print("Selected PDF:", filename)

# read the pages in from the PDF
sql = "SELECT * FROM doc_pages WHERE filename = '%s' ORDER BY _id;"  % filename

doc_pages = featurebase_query({"sql": sql}).get('results')

if not doc_pages:
	print("Please run `python3 index_pdfs.py` first to index `%s`." % filename)
	sys.exit()

# loop over the document's pages for processing
for page in doc_pages:
	# loop over the page's fragments (uuids from weaviate)
	for uuid in page.get('uuids'):
		# select the page's fragments from FeatureBase
		sql = "SELECT * FROM doc_fragments WHERE _id = '%s';" % uuid
		try:
			doc_fragments = featurebase_query({"sql": sql}).get('results')[0] # first and only result
		except Exception as ex:
			print(sql)
			print(ex)
			continue

		# get words from doc_fragments
		words = doc_fragments.get('fragment')

		# document info
		page_id = page.get('_id')
		page_num = page_id.split("_")[0]
		filename = page.get('filename')
		title = page.get('title')

		# status update
		print("system> Extracting for page %s of %s." % (page_num, filename))

		# handle periodic completion errors
		# AI completions need valid dictionaries, and sometimes GPT doesn't return a complete dict
		# we try 5 times, but usually trying just one more time works
		for x in range(5):
			# make sure we have enough to operate on
			if len(words) < 6:
				document.setdefault('error', "Not enough words.")
				print("system> Not enough words.")
				break

			# call the AI with a document containing "words"
			document = ai("gpt_keyterms", {"words": words})

			if not document.get('error', None) and document.get('keyterms'):
				break
			else:
				print("system> ", document.get('error'))
				print("system> Sleeping for 5 seconds and then trying again.")
				time.sleep(5)

		# if we don't have an error
		if not document.get('error', None):
			if document.get('keyterms') and document.get('question'):
				print("system> Keyterms found: ", ", ".join(document.get('keyterms')))
				print("system> Question formed: ", document.get('question'))
				print("system> Inserting into FeatureBase...")
				for keyterm in document.get('keyterms'):
					sql = "INSERT INTO doc_keyterms VALUES('%s', ['%s'], ['%s'], ['%s'], ['%s']);" % (keyterm.lower(), filename, title, uuid, page_id)
					featurebase_query({"sql": sql})

				# get question embedding (send in one get one back)
				question_embedding = embeddings([document.get('question')])[0]

				if len(question_embedding.get('embedding')) == 768:
					sql = f"INSERT INTO doc_questions VALUES('{uuid}', '{filename}', '{title}', '{document.get('question')}', {document.get('keyterms')}, '{page_id}', {question_embedding.get('embedding')});"
					featurebase_query({"sql": sql})
				else:
					print("system> Vectorization returned malformed vector. Skipping entry.")
			else:
				print("system> No keyterms or question found?")
				print(document.get('error'))
