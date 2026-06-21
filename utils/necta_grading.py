def calculate_o_level_grade(score, max_score=100):
    percentage = (score / max_score) * 100
    if percentage >= 75: return 'A'
    elif percentage >= 65: return 'B'
    elif percentage >= 45: return 'C'
    elif percentage >= 30: return 'D'
    else: return 'F'

def calculate_a_level_grade(score, max_score=100):
    percentage = (score / max_score) * 100
    if percentage >= 80: return 'A'
    elif percentage >= 70: return 'B'
    elif percentage >= 60: return 'C'
    elif percentage >= 50: return 'D'
    elif percentage >= 40: return 'E'
    elif percentage >= 35: return 'S'
    else: return 'F'

def calculate_o_level_points(grade):
    return {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'F': 5}.get(grade, 5)

def calculate_a_level_points(grade):
    return {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'S': 6, 'F': 7}.get(grade, 7)

def calculate_gpa(grades, level='O-LEVEL'):
    if not grades: return 0.0
    func = calculate_o_level_points if level == 'O-LEVEL' else calculate_a_level_points
    return round(sum(func(g) for g in grades) / len(grades), 2)

def determine_o_level_division(total_points, num_subjects):
    if num_subjects < 7: return 'INCOMPLETE'
    if 7 <= total_points <= 17: return 'I'
    elif 18 <= total_points <= 21: return 'II'
    elif 22 <= total_points <= 25: return 'III'
    elif 26 <= total_points <= 33: return 'IV'
    else: return '0'

def determine_a_level_division(core_grades):
    if len(core_grades) < 3: return 'INCOMPLETE'
    total = sum(calculate_a_level_points(g) for g in core_grades)
    if 3 <= total <= 9: return 'I'
    elif 10 <= total <= 12: return 'II'
    elif 13 <= total <= 17: return 'III'
    elif 18 <= total <= 21: return 'IV'
    else: return '0'

def get_competence_status(gpa, level='O-LEVEL'):
    """Competence based on GPA (Lower = Better)"""
    if level == 'A-LEVEL':
        if gpa <= 2.0: return 'EXCELLENT', '#006400'
        elif gpa <= 3.5: return 'VERY GOOD', '#00AA00'
        elif gpa <= 5.0: return 'GOOD', '#FFD700'
        elif gpa <= 6.0: return 'SATISFACTORY', '#FF8800'
        else: return 'FAIL', '#FF0000'
    else:
        if gpa <= 1.9: return 'EXCELLENT', '#006400'
        elif gpa <= 2.9: return 'VERY GOOD', '#00AA00'
        elif gpa <= 3.9: return 'GOOD', '#FFD700'
        elif gpa <= 4.4: return 'SATISFACTORY', '#FF8800'
        else: return 'FAIL', '#FF0000'

def get_grade_color(grade):
    return {'A': '#006600', 'B': '#00AA00', 'C': '#FFCC00', 'D': '#FF8800', 'E': '#FF6600', 'S': '#FF4400', 'F': '#FF0000'}.get(grade, '#000000')

def get_division_color(division):
    return {'I': '#006400', 'II': '#228B22', 'III': '#FFD700', 'IV': '#FF8C00', '0': '#FF0000'}.get(division, '#000000')

def format_detailed_subjects(subjects_dict):
    parts = []
    for code, data in sorted(subjects_dict.items()):
        parts.append(f"{data.get('short_code', code)}-'{data.get('grade', '-')}'")
    return ' '.join(parts)

def get_gpa_rating(gpa, level='O-LEVEL'):
    if level == 'A-LEVEL':
        if gpa <= 3.0: return 'OUTSTANDING'
        elif gpa <= 4.0: return 'VERY GOOD'
        elif gpa <= 5.0: return 'GOOD'
        elif gpa <= 6.0: return 'SATISFACTORY'
        else: return 'NEEDS IMPROVEMENT'
    else:
        if gpa <= 1.5: return 'OUTSTANDING'
        elif gpa <= 2.4: return 'EXCELLENT'
        elif gpa <= 3.1: return 'VERY GOOD'
        elif gpa <= 3.6: return 'GOOD'
        elif gpa <= 4.7: return 'SATISFACTORY'
        else: return 'NEEDS IMPROVEMENT'