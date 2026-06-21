O_LEVEL_SUBJECTS = {
    '011': {'name': 'HISTORIA YA TANZANIA NA MAADILI', 'short': 'HTM', 'category': 'COMPULSORY'},
    '012': {'name': 'HISTORY', 'short': 'HIST', 'category': 'OPTIONAL'},
    '013': {'name': 'GEOGRAPHY', 'short': 'GEO', 'category': 'COMPULSORY'},
    '021': {'name': 'KISWAHILI', 'short': 'KISW', 'category': 'COMPULSORY'},
    '022': {'name': 'ENGLISH', 'short': 'ENG', 'category': 'COMPULSORY'},
    '031': {'name': 'PHYSICS', 'short': 'PHY', 'category': 'OPTIONAL'},
    '032': {'name': 'CHEMISTRY', 'short': 'CHEM', 'category': 'OPTIONAL'},
    '033': {'name': 'BIOLOGY', 'short': 'BIO', 'category': 'OPTIONAL'},
    '041': {'name': 'MATHEMATICS', 'short': 'MATH', 'category': 'COMPULSORY'},
    '062': {'name': 'BOOK KEEPING', 'short': 'B/KEEPING', 'category': 'OPTIONAL'},
    '065': {'name': 'BUSINESS STUDY', 'short': 'B/STUDY', 'category': 'COMPULSORY'},
}

O_LEVEL_COMPULSORY = ['011', '013', '021', '022', '041', '065']

O_LEVEL_OPTIONAL_GROUPS = {
    'HISTORY_BOOKKEEPING': ['012', '062'],
    'PHYSICS_CHEMISTRY': ['031', '032'],
    'PHYSICS_BIOLOGY': ['031', '033'],
    'CHEMISTRY_BIOLOGY': ['032', '033'],
    'PHYSICS_CHEMISTRY_BIOLOGY': ['031', '032', '033'],
}

A_LEVEL_SUBJECTS = {
    '111': {'name': 'HISTORY', 'short': 'HIST', 'category': 'CORE'},
    '112': {'name': 'GEOGRAPHY', 'short': 'GEO', 'category': 'CORE'},
    '121': {'name': 'KISWAHILI', 'short': 'KISW', 'category': 'CORE'},
    '122': {'name': 'ENGLISH LANGUAGE', 'short': 'ENG', 'category': 'CORE'},
    '131': {'name': 'PHYSICS', 'short': 'PHY', 'category': 'CORE'},
    '132': {'name': 'CHEMISTRY', 'short': 'CHEM', 'category': 'CORE'},
    '133': {'name': 'BIOLOGY', 'short': 'BIO', 'category': 'CORE'},
    '141': {'name': 'ADVANCED MATHEMATICS', 'short': 'AMATH', 'category': 'CORE'},
    '150': {'name': 'HISTORIA YA TANZANIA NA MAADILI', 'short': 'HTM', 'category': 'SUBSIDIARY'},
    '151': {'name': 'ACADEMIC COMMUNICATION', 'short': 'ACOMM', 'category': 'SUBSIDIARY'},
    '152': {'name': 'BASIC APPLIED MATHEMATICS', 'short': 'BAM', 'category': 'SUBSIDIARY'},
}

A_LEVEL_COMBINATIONS = {
    'HGK': {'name': 'HISTORY, GEOGRAPHY, KISWAHILI', 'core': ['111', '112', '121'], 'subsidiary': ['150', '151']},
    'HKL': {'name': 'HISTORY, KISWAHILI, ENGLISH LANGUAGE', 'core': ['111', '121', '122'], 'subsidiary': ['150', '151']},
    'CBG': {'name': 'CHEMISTRY, BIOLOGY, GEOGRAPHY', 'core': ['132', '133', '112'], 'subsidiary': ['150', '151', '152']},
    'PCB': {'name': 'PHYSICS, CHEMISTRY, BIOLOGY', 'core': ['131', '132', '133'], 'subsidiary': ['150', '151', '152']},
    'PCM': {'name': 'PHYSICS, CHEMISTRY, ADVANCED MATHEMATICS', 'core': ['131', '132', '141'], 'subsidiary': ['150', '151']},
}

# ==================== OLD CURRICULUM (O-LEVEL ONLY) ====================
# Same subject codes, different compulsory/optional arrangement
# 7 Compulsory + 3 Optional (students can take any number of optional)

OLD_CURRICULUM_CONFIG = {
    'compulsory': ['201', '021', '041', '013', '022', '012', '033'],
    'optional': ['031', '032', '024'],
    'subjects': {
        '201': {'name': 'CIVICS', 'short': 'CIV'},
        '021': {'name': 'KISWAHILI', 'short': 'KISW'},
        '041': {'name': 'BASIC MATHEMATICS', 'short': 'BMATH'},
        '013': {'name': 'GEOGRAPHY', 'short': 'GEO'},
        '022': {'name': 'ENGLISH', 'short': 'ENG'},
        '012': {'name': 'HISTORY', 'short': 'HIST'},
        '033': {'name': 'BIOLOGY', 'short': 'BIO'},
        '031': {'name': 'PHYSICS', 'short': 'PHY'},
        '032': {'name': 'CHEMISTRY', 'short': 'CHEM'},
        '024': {'name': 'LITERATURE IN ENGLISH', 'short': 'LIT'},
    }
}