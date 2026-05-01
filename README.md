# allmydox
write a python software to 
extract information about documents to a sqlite database
0. create a sqlite database
1. list all documents in one table and create an ID (fileID, filename, folderpath, size, extension)
2. list all nouns that appear in the documents in one table an giv it an ID (nounID, noun)
3. list all occurences of the nouns in another table (nounOccuranceID, fileID, nounID, Pagenumber, position)
4. list all names that appear in the documents in one table an giv it an ID (nameID, name)
5. list all occurences of the names in another table (nameOccuranceID,fileID, nameID, Pagenumber, position)
4. list all verbs that appear in the documents in one table an giv it an ID (verbID, noun)
5. list all occurences of the verbs in another table (verbOccuranceID,fileID, verbID, Pagenumber, position)
6. list all nouns and names, that occour in the same sentence together in one table (nounsentenceID, nounOccuranceID, nounOccuranceID)
7. list all nouns and names, that occour in the same paragraph together in one table (nounparagraphID, nounOccuranceID, nounOccuranceID)
8. list all nouns and names that occour in the same sentence with one verb together in one table (nounverbsentenceID, nounOccuranceID, verbOccuranceID)
