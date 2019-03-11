import os
import re
import csv
import sys
import uuid
import rdflib
import getopt
import subprocess
from rdflib.plugins.sparql import prepareQuery
from configparser import ConfigParser, ExtendedInterpolation
from rdfizer.triples_map import TriplesMap as tm
import traceback
from mysql import connector

try:
	from triples_map import TriplesMap as tm
except:
	from .triples_map import TriplesMap as tm	

# Work in the rr:sqlQuery (change mapping parser query, add sqlite3 support, etc)
# Work in the "when subject is empty" thing (uuid.uuid4(), dependency graph over the ) 

def count_characters(string):
	count = 0
	for s in string:
		if s == "{":
			count += 1
	return count

def clean_URL_suffix(URL_suffix):
    cleaned_URL=""
    if "http" in URL_suffix:
    	return URL_suffix

    for c in URL_suffix:
        if c.isalpha() or c.isnumeric() or c =='_' or c=='-' or c == '(' or c == ')':
            cleaned_URL= cleaned_URL+c
        if c == "/" or c == "\\":
            cleaned_URL = cleaned_URL+"-"

    return cleaned_URL

def string_separetion(string):
	if ("{" in string) and ("[" in string):
		prefix = string.split("{")[0]
		condition = string.split("{")[1].split("}")[0]
		postfix = string.split("{")[1].split("}")[1]
		field = prefix + "*" + postfix
	elif "[" in string:
		return string, string
	else:
		return string, ""
	return string, condition

def condition_separetor(string):
	condition_field = string.split("[")
	field = condition_field[1][:len(condition_field[1])-1].split("=")[0]
	value = condition_field[1][:len(condition_field[1])-1].split("=")[1]
	return field, value

def mapping_parser(mapping_file):

	"""
	(Private function, not accessible from outside this package)

	Takes a mapping file in Turtle (.ttl) or Notation3 (.n3) format and parses it into a list of
	TriplesMap objects (refer to TriplesMap.py file)

	Parameters
	----------
	mapping_file : string
		Path to the mapping file

	Returns
	-------
	A list of TriplesMap objects containing all the parsed rules from the original mapping file
	"""

	mapping_graph = rdflib.Graph()

	try:
		mapping_graph.load(mapping_file, format='n3')
	except Exception as n3_mapping_parse_exception:
		print(n3_mapping_parse_exception)
		print('Could not parse {} as a mapping file'.format(mapping_file))
		print('Aborting...')
		sys.exit(1)

	mapping_query = """
		prefix rr: <http://www.w3.org/ns/r2rml#> 
		prefix rml: <http://semweb.mmlab.be/ns/rml#> 
		prefix ql: <http://semweb.mmlab.be/ns/ql#> 
		SELECT DISTINCT *
		WHERE {

	# Subject -------------------------------------------------------------------------
			?triples_map_id rml:logicalSource ?_source .
			?_source rml:source ?data_source .
			?_source rml:referenceFormulation ?ref_form .
			OPTIONAL { ?_source rml:iterator ?iterator . }
			
			?triples_map_id rr:subjectMap ?_subject_map .
			?_subject_map rr:template ?subject_template .
			OPTIONAL { ?_subject_map rr:class ?rdf_class . }

	# Predicate -----------------------------------------------------------------------
			?triples_map_id rr:predicateObjectMap ?_predicate_object_map .
			OPTIONAL {
				?triples_map_id rr:predicateObjectMap ?_predicate_object_map .
				?_predicate_object_map rr:predicateMap ?_predicate_map .
				?_predicate_map rr:constant ?predicate_constant .
			}
			OPTIONAL {
				?_predicate_object_map rr:predicateMap ?_predicate_map .
				?_predicate_map rr:template ?predicate_template .
			}
			OPTIONAL {
				?_predicate_object_map rr:predicateMap ?_predicate_map .
				?_predicate_map rml:reference ?predicate_reference .
			}
			OPTIONAL {
				?_predicate_object_map rr:predicate ?predicate_constant_shortcut .
			}

	# Object --------------------------------------------------------------------------
			OPTIONAL {
				?_predicate_object_map rr:objectMap ?_object_map .
				?_object_map rr:constant ?object_constant .
				OPTIONAL {
					?_object_map rr:datatype ?object_datatype .
				}
			}
			OPTIONAL {
				?_predicate_object_map rr:objectMap ?_object_map .
				?_object_map rr:template ?object_template .
				OPTIONAL {
					?_object_map rr:datatype ?object_datatype .
				}
			}
			OPTIONAL {
				?_predicate_object_map rr:objectMap ?_object_map .
				?_object_map rml:reference ?object_reference .
				OPTIONAL {
					?_object_map rr:datatype ?object_datatype .
				}
			}
			OPTIONAL {
				?_predicate_object_map rr:objectMap ?_object_map .
				?_object_map rr:parentTriplesMap ?object_parent_triples_map .
			}
			OPTIONAL {
				?_predicate_object_map rr:object ?object_constant_shortcut .
				OPTIONAL {
					?_object_map rr:datatype ?object_datatype .
				}
			}
		} """

	mapping_query_results = mapping_graph.query(mapping_query)
	triples_map_list = []

	for result_triples_map in mapping_query_results:
		triples_map_exists = False
		for triples_map in triples_map_list:
			triples_map_exists = triples_map_exists or (str(triples_map.triples_map_id) == str(result_triples_map.triples_map_id))
		
		if not triples_map_exists:
			if result_triples_map.rdf_class is None:
				reference, condition = string_separetion(str(result_triples_map.subject_template))
				subject_map = tm.SubjectMap(str(result_triples_map.subject_template), condition, result_triples_map.rdf_class)
			else:
				reference, condition = string_separetion(str(result_triples_map.subject_template))
				subject_map = tm.SubjectMap(str(result_triples_map.subject_template), condition, str(result_triples_map.rdf_class))
				
			mapping_query_prepared = prepareQuery(mapping_query)
			mapping_query_prepared_results = mapping_graph.query(mapping_query_prepared, initBindings={'triples_map_id': result_triples_map.triples_map_id})

			predicate_object_maps_list = []

			for result_predicate_object_map in mapping_query_prepared_results:
				if result_predicate_object_map.predicate_constant is not None:
					predicate_map = tm.PredicateMap("constant", str(result_predicate_object_map.predicate_constant), "")
				elif result_predicate_object_map.predicate_constant_shortcut is not None:
					predicate_map = tm.PredicateMap("constant shortcut", str(result_predicate_object_map.predicate_constant_shortcut), "")
				elif result_predicate_object_map.predicate_template is not None:
					template, condition = string_separetion(str(result_predicate_object_map.predicate_template))
					predicate_map = tm.PredicateMap("template", template, condition)
				elif result_predicate_object_map.predicate_reference is not None:
					reference, condition = string_separetion(str(result_predicate_object_map.predicate_reference))
					predicate_map = tm.PredicateMap("reference", reference, condition)
				else:
					print("Invalid predicate map")
					print("Aborting...")
					sys.exit(1)

				if result_predicate_object_map.object_constant is not None:
					object_map = tm.ObjectMap("constant", str(result_predicate_object_map.object_constant), str(result_predicate_object_map.object_datatype))
				elif result_predicate_object_map.object_template is not None:
					object_map = tm.ObjectMap("template", str(result_predicate_object_map.object_template), str(result_predicate_object_map.object_datatype))
				elif result_predicate_object_map.object_reference is not None:
					object_map = tm.ObjectMap("reference", str(result_predicate_object_map.object_reference), str(result_predicate_object_map.object_datatype))
				elif result_predicate_object_map.object_parent_triples_map is not None:
					object_map = tm.ObjectMap("parent triples map", str(result_predicate_object_map.object_parent_triples_map), str(result_predicate_object_map.object_datatype))
				elif result_predicate_object_map.object_constant_shortcut is not None:
					object_map = tm.ObjectMap("constant shortcut", str(result_predicate_object_map.object_constant_shortcut), str(result_predicate_object_map.object_datatype))
				else:
					print("Invalid object map")
					print("Aborting...")
					sys.exit(1)

				predicate_object_maps_list += [tm.PredicateObjectMap(predicate_map, object_map)]

			current_triples_map = tm.TriplesMap(str(result_triples_map.triples_map_id), str(result_triples_map.data_source), subject_map, predicate_object_maps_list, ref_form=str(result_triples_map.ref_form), iterator=str(result_triples_map.iterator))
			triples_map_list += [current_triples_map]

	return triples_map_list

def string_substitution(string, pattern, row, term):

	"""
	(Private function, not accessible from outside this package)

	Takes a string and a pattern, matches the pattern against the string and perform the substitution
	in the string from the respective value in the row.

	Parameters
	----------
	string : string
		String to be matched
	triples_map_list : string
		Pattern containing a regular expression to match
	row : dictionary
		Dictionary with CSV headers as keys and fields of the row as values

	Returns
	-------
	A string with the respective substitution if the element to be subtitued is not invalid
	(i.e.: empty string, string with just spaces, just tabs or a combination of both), otherwise
	returns None
	"""

	template_references = re.finditer(pattern, string)
	new_string = string
	offset_current_substitution = 0
	for reference_match in template_references:
		start, end = reference_match.span()[0], reference_match.span()[1]
		if pattern == "{(.+?)}":
			match = reference_match.group(1).split("[")[0]
			if row[match] is not None:
				if re.search("^[\s|\t]*$", row[match]) is None:
					new_string = new_string[:start + offset_current_substitution] + clean_URL_suffix(row[match].strip()) + new_string[ end + offset_current_substitution:]
					offset_current_substitution = offset_current_substitution + len(row[match]) - (end - start)
				else:
					return None
				# To-do:
				# Generate blank node when subject in csv is not a valid string (empty string, just spaces, just tabs or a combination of the last two)
				#if term == "subject":
				#	new_string = new_string[:start + offset_current_substitution] + str(uuid.uuid4()) + new_string[end + offset_current_substitution:]
				#	offset_current_substitution = offset_current_substitution + len(row[match]) - (end - start)
				#else:
				#	return None
		elif pattern == ".+":
			match = reference_match.group(0)
			if row[match] is not None:
				if re.search("^[\s|\t]*$", row[match]) is None:
					new_string = new_string[:start] + row[match].strip().replace("\"", "'") + new_string[end:]
					new_string = "\"" + new_string + "\"" if new_string[0] != "\"" and new_string[-1] != "\"" else new_string
				else:
					return None
		else:
			print("Invalid pattern")
			print("Aborting...")
			sys.exit(1)

	return new_string

def string_substitution_array(string, pattern, row, row_headers, term):

	"""
	(Private function, not accessible from outside this package)

	Takes a string and a pattern, matches the pattern against the string and perform the substitution
	in the string from the respective value in the row.

	Parameters
	----------
	string : string
		String to be matched
	triples_map_list : string
		Pattern containing a regular expression to match
	row : dictionary
		Dictionary with CSV headers as keys and fields of the row as values

	Returns
	-------
	A string with the respective substitution if the element to be subtitued is not invalid
	(i.e.: empty string, string with just spaces, just tabs or a combination of both), otherwise
	returns None
	"""

	template_references = re.finditer(pattern, string)
	new_string = string
	offset_current_substitution = 0
	for reference_match in template_references:
		start, end = reference_match.span()[0], reference_match.span()[1]
		if pattern == "{(.+?)}":
			match = reference_match.group(1).split("[")[0]
			if match in row_headers:
				if row[row_headers.index(match)] is not None:
					value = row[row_headers.index(match)]
					if type(value) is int:
						value = str(value)
					if re.search("^[\s|\t]*$", value) is None:
						new_string = new_string[:start + offset_current_substitution] + value.strip() + new_string[ end + offset_current_substitution:]
						offset_current_substitution = offset_current_substitution + len(value) - (end - start)
					else:
						return None
			else:
				return None
				# To-do:
				# Generate blank node when subject in csv is not a valid string (empty string, just spaces, just tabs or a combination of the last two)
				#if term == "subject":
				#	new_string = new_string[:start + offset_current_substitution] + str(uuid.uuid4()) + new_string[end + offset_current_substitution:]
				#	offset_current_substitution = offset_current_substitution + len(row[match]) - (end - start)
				#else:
				#	return None
		elif pattern == ".+":
			match = reference_match.group(0)
			if match in row_headers:
				if row[row_headers.index(match)] is not None:
					value = row[row_headers.index(match)]
					if type(value) is int:
						value = str(value)
					if re.search("^[\s|\t]*$", value) is None:
						new_string = new_string[:start] + value.strip().replace("\"", "'") + new_string[end:]
						new_string = "\"" + new_string + "\"" if new_string[0] != "\"" and new_string[-1] != "\"" else new_string
					else:
						return None
				else:
					return None
			else:
				return None
		else:
			print("Invalid pattern")
			print("Aborting...")
			sys.exit(1)

	return new_string

def semantify_json(triples_map, triples_map_list, output_file_descriptor):
	
	with open(str(triples_map.data_source), "rb") as input_file_descriptor:
		data = json.load(input_file_descriptor)
		for row in data:
			if triples_map.subject_map.condition == "":
				try:
					subject = "<" + string_substitution(triples_map.subject_map.value, "{(.+?)}", row, "subject") + ">"
				except:
					subject = None
			else:
				field, condition = condition_separetor(triples_map.subject_map.condition)
				if row[field] == condition:
					try:
						subject = "<" + string_substitution(triples_map.subject_map.value, "{(.+?)}", row, "subject") + ">"
					except:
						subject = None
				else:
					subject = None

			if subject is None:
				continue

			if triples_map.subject_map.rdf_class is not None:
				output_file_descriptor.write(subject + " <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> " + "<{}> .\n".format(triples_map.subject_map.rdf_class))


			for predicate_object_map in triples_map.predicate_object_maps_list:
				if predicate_object_map.predicate_map.mapping_type == "constant" or predicate_object_map.predicate_map.mapping_type == "constant shortcut":
					predicate = "<" + predicate_object_map.predicate_map.value + ">"
				elif predicate_object_map.predicate_map.mapping_type == "template":
					if predicate_object_map.predicate_map.condition != "":
							field, condition = condition_separetor(predicate_object_map.predicate_map.condition)
							if row[field] == condition:
								try:
									predicate = "<" + string_substitution(predicate_object_map.predicate_map.value, "{(.+?)}", row, "predicate") + ">"
								except:
									predicate = None
							else:
								predicate = None
					else:
						try:
							predicate = "<" + string_substitution(predicate_object_map.predicate_map.value, "{(.+?)}", row, "predicate") + ">"
						except:
							predicate = None
				elif predicate_object_map.predicate_map.mapping_type == "reference":
						if predicate_object_map.predicate_map.condition != "":
							field, condition = condition_separetor(predicate_object_map.predicate_map.condition)
							if row[field] == condition:
								predicate = string_substitution(predicate_object_map.predicate_map.value, ".+", row, "predicate")
							else:
								predicate = None
						else:
							predicate = string_substitution(predicate_object_map.predicate_map.value, ".+", row, "predicate")
				else:
					print("Invalid predicate mapping type")
					print("Aborting...")
					sys.exit(1)

				if predicate_object_map.object_map.mapping_type == "constant" or predicate_object_map.object_map.mapping_type == "constant shortcut":
					object = "<" + predicate_object_map.object_map.value + ">"
				elif predicate_object_map.object_map.mapping_type == "template":
					try:
						object = "<" + string_substitution(predicate_object_map.object_map.value, "{(.+?)}", row, "object") + ">"
					except TypeError:
						object = None
				elif predicate_object_map.object_map.mapping_type == "reference":
					object = string_substitution(predicate_object_map.object_map.value, ".+", row, "object")
				elif predicate_object_map.object_map.mapping_type == "parent triples map":
					for triples_map_element in triples_map_list:
						if triples_map_element.triples_map_id == predicate_object_map.object_map.value:
							if triples_map_element.data_source != triples_map.data_source:
								print("Warning: Join condition between different data sources is not implemented yet,")
								print("         triples for this triples-map will be generated without the predicate-object-maps")
								print("         that require a join condition between data sources")
								object = None
							else:
								try:
									object = "<" + string_substitution(triples_map_element.subject_map.value, "{(.+?)}", row, "object") + ">"
								except TypeError:
									object = None
							break
						else:
							continue
				else:
					print("Invalid object mapping type")
					print("Aborting...")
					sys.exit(1)

				if object is not None and predicate_object_map.object_map.datatype is not None:
					object += "^^<{}>".format(predicate_object_map.object_map.datatype)

				if predicate is not None and object is not None:
					triple = subject + " " + predicate + " " + object + " .\n"
					output_file_descriptor.write(triple)
				else:
					continue

def semantify_csv(triples_map, triples_map_list, delimiter, output_file_descriptor):

	"""
	(Private function, not accessible from outside this package)

	Takes a triples-map rule and applies it to each one of the rows of its CSV data
	source

	Parameters
	----------
	triples_map : TriplesMap object
		Mapping rule consisting of a logical source, a subject-map and several predicateObjectMaps
		(refer to the TriplesMap.py file in the triplesmap folder)
	triples_map_list : list of TriplesMap objects
		List of triples-maps parsed from current mapping being used for the semantification of a
		dataset (mainly used to perform rr:joinCondition mappings)
	delimiter : string
		Delimiter value for the CSV or TSV file ("\s" and "\t" respectively)
	output_file_descriptor : file object 
		Descriptor to the output file (refer to the Python 3 documentation)

	Returns
	-------
	An .nt file per each dataset mentioned in the configuration file semantified.
	If the duplicates are asked to be removed in main memory, also returns a -min.nt
	file with the triples sorted and with the duplicates removed.
	"""

	with open(str(triples_map.data_source), "r") as input_file_descriptor:
		reader = csv.DictReader(input_file_descriptor, delimiter=delimiter)
		for row in reader:
			if triples_map.subject_map.condition == "":
				try:
					subject = "<" + string_substitution(triples_map.subject_map.value, "{(.+?)}", row, "subject") + ">"
				except:
					subject = None
			else:
				field, condition = condition_separetor(triples_map.subject_map.condition)
				if row[field] == condition:
					try:
						subject = "<" + string_substitution(triples_map.subject_map.value, "{(.+?)}", row, "subject") + ">"
					except:
						subject = None
				else:
					subject = None

			if subject is None:
				continue

			if triples_map.subject_map.rdf_class is not None:
				output_file_descriptor.write(subject + " <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> " + "<{}> .\n".format(triples_map.subject_map.rdf_class))


			for predicate_object_map in triples_map.predicate_object_maps_list:
				if predicate_object_map.predicate_map.mapping_type == "constant" or predicate_object_map.predicate_map.mapping_type == "constant shortcut":
					predicate = "<" + predicate_object_map.predicate_map.value + ">"
				elif predicate_object_map.predicate_map.mapping_type == "template":
					if predicate_object_map.predicate_map.condition != "":
							field, condition = condition_separetor(predicate_object_map.predicate_map.condition)
							if row[field] == condition:
								try:
									predicate = "<" + string_substitution(predicate_object_map.predicate_map.value, "{(.+?)}", row, "predicate") + ">"
								except:
									predicate = None
							else:
								predicate = None
					else:
						try:
							predicate = "<" + string_substitution(predicate_object_map.predicate_map.value, "{(.+?)}", row, "predicate") + ">"
						except:
							predicate = None
				elif predicate_object_map.predicate_map.mapping_type == "reference":
						if predicate_object_map.predicate_map.condition != "":
							field, condition = condition_separetor(predicate_object_map.predicate_map.condition)
							if row[field] == condition:
								predicate = string_substitution(predicate_object_map.predicate_map.value, ".+", row, "predicate")
							else:
								predicate = None
						else:
							predicate = string_substitution(predicate_object_map.predicate_map.value, ".+", row, "predicate")
				else:
					print("Invalid predicate mapping type")
					print("Aborting...")
					sys.exit(1)

				if predicate_object_map.object_map.mapping_type == "constant" or predicate_object_map.object_map.mapping_type == "constant shortcut":
					object = "<" + predicate_object_map.object_map.value + ">"
				elif predicate_object_map.object_map.mapping_type == "template":
					try:
						object = "<" + string_substitution(predicate_object_map.object_map.value, "{(.+?)}", row, "object") + ">"
					except TypeError:
						object = None
				elif predicate_object_map.object_map.mapping_type == "reference":
					object = string_substitution(predicate_object_map.object_map.value, ".+", row, "object")
				elif predicate_object_map.object_map.mapping_type == "parent triples map":
					for triples_map_element in triples_map_list:
						if triples_map_element.triples_map_id == predicate_object_map.object_map.value:
							if triples_map_element.data_source != triples_map.data_source:
								print("Warning: Join condition between different data sources is not implemented yet,")
								print("         triples for this triples-map will be generated without the predicate-object-maps")
								print("         that require a join condition between data sources")
								object = None
							else:
								try:
									object = "<" + string_substitution(triples_map_element.subject_map.value, "{(.+?)}", row, "object") + ">"
								except TypeError:
									object = None
							break
						else:
							continue
				else:
					print("Invalid object mapping type")
					print("Aborting...")
					sys.exit(1)

				if object is not None and predicate_object_map.object_map.datatype is not None:
					object += "^^<{}>".format(predicate_object_map.object_map.datatype)

				if predicate is not None and object is not None:
					triple = subject + " " + predicate + " " + object + " .\n"
					output_file_descriptor.write(triple)
				else:
					continue

def semantify_mysql(row, row_headers, triples_map, triples_map_list, output_file_descriptor):

	"""
	(Private function, not accessible from outside this package)

	Takes a triples-map rule and applies it to each one of the rows of its CSV data
	source

	Parameters
	----------
	triples_map : TriplesMap object
		Mapping rule consisting of a logical source, a subject-map and several predicateObjectMaps
		(refer to the TriplesMap.py file in the triplesmap folder)
	triples_map_list : list of TriplesMap objects
		List of triples-maps parsed from current mapping being used for the semantification of a
		dataset (mainly used to perform rr:joinCondition mappings)
	delimiter : string
		Delimiter value for the CSV or TSV file ("\s" and "\t" respectively)
	output_file_descriptor : file object 
		Descriptor to the output file (refer to the Python 3 documentation)

	Returns
	-------
	An .nt file per each dataset mentioned in the configuration file semantified.
	If the duplicates are asked to be removed in main memory, also returns a -min.nt
	file with the triples sorted and with the duplicates removed.
	"""


	if triples_map.subject_map.condition == "":
		try:
			subject = "<" + string_substitution_array(triples_map.subject_map.value, "{(.+?)}", row, row_headers, "subject") + ">"
		except:
			subject = None
	else:
		try:
			subject = "<" + string_substitution_array(triples_map.subject_map.value, "{(.+?)}", row, row_headers, "subject") + ">"
		except:
			subject = None

	if subject is None:
		pass

	if triples_map.subject_map.rdf_class is not None and subject is not None:
		output_file_descriptor.write(subject + " <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> " + "<{}> .\n".format(triples_map.subject_map.rdf_class))


	for predicate_object_map in triples_map.predicate_object_maps_list:
		if predicate_object_map.predicate_map.mapping_type == "constant" or predicate_object_map.predicate_map.mapping_type == "constant shortcut":
			predicate = "<" + predicate_object_map.predicate_map.value + ">"
		elif predicate_object_map.predicate_map.mapping_type == "template":
			if predicate_object_map.predicate_map.condition != "":
				try:
					predicate = "<" + string_substitution_array(predicate_object_map.predicate_map.value, "{(.+?)}", row, row_headers, "predicate") + ">"
				except:
					predicate = None
			else:
				try:
					predicate = "<" + string_substitution_array(predicate_object_map.predicate_map.value, "{(.+?)}", row, row_headers, "predicate") + ">"
				except:
					predicate = None
		elif predicate_object_map.predicate_map.mapping_type == "reference":
				if predicate_object_map.predicate_map.condition != "":
					predicate = string_substitution_array(predicate_object_map.predicate_map.value, ".+", row, row_headers, "predicate")
		else:
			print("Invalid predicate mapping type")
			print("Aborting...")
			sys.exit(1)

		if predicate_object_map.object_map.mapping_type == "constant" or predicate_object_map.object_map.mapping_type == "constant shortcut":
			object = "<" + predicate_object_map.object_map.value + ">"
		elif predicate_object_map.object_map.mapping_type == "template":
			try:
				object = "<" + string_substitution_array(predicate_object_map.object_map.value, "{(.+?)}", row, row_headers, "object") + ">"
			except TypeError:
				object = None
		elif predicate_object_map.object_map.mapping_type == "reference":
			object = string_substitution_array(predicate_object_map.object_map.value, ".+", row, row_headers, "object")
		elif predicate_object_map.object_map.mapping_type == "parent triples map":
			for triples_map_element in triples_map_list:
				if triples_map_element.triples_map_id == predicate_object_map.object_map.value:
					if triples_map_element.data_source != triples_map.data_source:
						print("Warning: Join condition between different data sources is not implemented yet,")
						print("         triples for this triples-map will be generated without the predicate-object-maps")
						print("         that require a join condition between data sources")
						object = None
					else:
						try:
							object = "<" + string_substitution_array(triples_map_element.subject_map.value, "{(.+?)}", row, row_headers, "object") + ">"
						except TypeError:
							object = None
					break
				else:
					continue
		else:
			print("Invalid object mapping type")
			print("Aborting...")
			sys.exit(1)

		if object is not None and predicate_object_map.object_map.datatype is not None:
			object += "^^<{}>".format(predicate_object_map.object_map.datatype)

		if predicate is not None and object is not None and subject is not None:
			triple = subject + " " + predicate + " " + object + " .\n"
			output_file_descriptor.write(triple)
		else:
			continue


def translate_sql(triples_map_list):

	query_list = []
	
	for triples_map in triples_map_list:
		proyections = []

		
		if "{" in triples_map.subject_map.value:
			subject = triples_map.subject_map.value
			count = count_characters(subject)
			if (count == 1) and (subject.split("{")[1].split("}")[0] not in proyections):
				subject = subject.split("{")[1].split("}")[0]
				if "[" in subject:
					subject = subject.split("[")[0]
				proyections.append(subject)
			elif count > 1:
				subject_list = subject.split("{")
				for s in subject_list:
					if "}" in s:
						subject = s.split("}")[0]
						if "[" in subject:
							subject = subject.split("[")
						if subject not in proyections:
							proyections.append(subject)

		for po in triples_map.predicate_object_maps_list:
			if "{" in po.object_map.value:
				predicate = po.object_map.value.split("{")[1].split("}")[0]
				if "[" in predicate:
					predicate = predicate.split("[")[0]
			elif "#" in po.object_map.value:
				pass
			else:
				predicate = po.object_map.value 
				if "[" in predicate:
					predicate = predicate.split("[")[0]

			if predicate not in proyections:
				proyections.append(predicate)

		temp_query = "SELECT "
		for p in proyections:
			if p == proyections[len(proyections)-1]:
			  	temp_query += p
			else:
				temp_query += p + ", "   

		temp_query = temp_query + " FROM " + triples_map.data_source + ";"
		query_list.append(temp_query)

	return triples_map.iterator, query_list

def semantify(config_path):

	"""
	Takes the configuration file path and sets the necessary variables to perform the
	semantification of each dataset presented in said file.

	Given a TTL/N3 mapping file expressing the correspondance rules between the raw
	data and the desired semantified data, the main function performs all the
	necessary operations to do this transformation

	Parameters
	----------
	config_path : string
		Path to the configuration file

	Returns
	-------
	An .nt file per each dataset mentioned in the configuration file semantified.
	If the duplicates are asked to be removed in main memory, also returns a -min.nt
	file with the triples sorted and with the duplicates removed.

	(No variable returned)
	
	"""

	config = ConfigParser(interpolation=ExtendedInterpolation())
	config.read(config_path)

	for dataset_number in range(int(config["datasets"]["number_of_datasets"])):
		if not os.path.exists(config["datasets"]["output_folder"]):
			os.mkdir(config["datasets"]["output_folder"])
		dataset_i = "dataset" + str(int(dataset_number) + 1)
		triples_map_list = mapping_parser(config[dataset_i]["mapping"])
		output_file = config["datasets"]["output_folder"] + "/" + config[dataset_i]["name"] + ".nt"
		if config[dataset_i]["format"] != "MySQL": 
			print("Semantifying {}.{}...".format(config[dataset_i]["name"], config[dataset_i]["format"]))
		else:
			print("Semantifying MySQL data")
		
		with open(output_file, "w") as output_file_descriptor:
			for triples_map in triples_map_list:
				if str(triples_map.file_format).lower() == "csv" and config[dataset_i]["format"].lower() == "csv":
					semantify_csv(triples_map, triples_map_list, ",", output_file_descriptor)
				#elif str(triples_map.file_format).lower() == "csv" and config[dataset_i]["format"].lower() == "tsv":
				#	semantify_csv(triples_map, triples_map_list, "\t", output_file_descriptor)
				elif triples_map.file_format == "JSONPath":
					semantify_json(triples_map, triples_map_list, output_file_descriptor)
				elif config[dataset_i]["format"] == "MySQL":
					database, query_list = translate_sql(triples_map_list)
					db = connector.connect(host=config[dataset_i]["host"], port=int(config[dataset_i]["port"]),user=config[dataset_i]["user"], password=config[dataset_i]["password"])
					cursor = db.cursor()
					cursor.execute("use " + database)
					for query in query_list:
						cursor.execute(query)
						row_headers=[x[0] for x in cursor.description]
						for row in cursor:
							semantify_mysql(row, row_headers, triples_map, triples_map_list, output_file_descriptor)
				else:
					print("Invalid reference formulation or format")
					print("Aborting...")
					sys.exit(1)

		if config[dataset_i]["remove_duplicate_triples_in_memory"].lower() == "yes":
			output_file_name = output_file = config["datasets"]["output_folder"] + "/" + config[dataset_i]["name"]
			cmd = 'sort -u {} > {}'.format(output_file_name + ".nt", output_file + "-min.nt")
			subprocess.call(cmd, shell=True)

		print("Successfully semantified {}.{}\n".format(config[dataset_i]["name"], config[dataset_i]["format"]))

def main():

	"""
	Function executed when the current file is executed as a script, instead of being
	executed as a Python package in another script.

	When executing the current file as a script in the terminal, the following flags
	are accepted:

	-h (python3 semantify.py -h): prompts the correct use of semantify.py as a script
	-c (python3 semantify.py -c <config_file>): executes the program as a script with
		with the <config_file> parameter as the path to the configuration file to be
		used
	--config_file (python3 semantify.py --config_file <config_file>): same behaviour
		as -c flag

	Parameters
	----------
	Nothing

	Returns
	-------
	Nothing

	"""

	argv = sys.argv[1:]
	try:
		opts, args = getopt.getopt(argv, 'hc:', 'config_file=')
	except getopt.GetoptError:
		print('python3 semantify.py -c <config_file>')
		sys.exit(1)
	for opt, arg in opts:
		if opt == '-h':
			print('python3 semantify.py -c <config_file>')
			sys.exit()
		elif opt == '-c' or opt == '--config_file':
			config_path = arg

	semantify(config_path)

if __name__ == "__main__":
	main()

"""
According to the meeting held on 11.04.2018, semantifying json files is not a top priority right
now, thus the reimplementation of following functions remain largely undocumented and unfinished.

def json_generator(file_descriptor, iterator):
	if len(iterator) != 0:
		if "[*]" not in iterator[0] and iterator[0] != "$":
			yield from json_generator(file_descriptor[iterator[0]], iterator[1:])
		elif "[*]" not in iterator[0] and iterator[0] == "$":
			yield from json_generator(file, iterator[1:])
		elif "[*]" in iterator[0] and "$" not in iterator[0]:
			file_array = file_descriptor[iterator[0].replace("[*]","")]
			for array_elem in file_array:
				yield from json_generator(array_elem, iterator[1:])
		elif iterator[0] == "$[*]":
			for array_elem in file_descriptor:
				yield from json_generator(array_elem, iterator[1:])
	else:
		yield file_descriptor


"""