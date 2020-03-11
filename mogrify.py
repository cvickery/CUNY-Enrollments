#! /usr/local/bin/python3
""" Transform CUNY enrollment query into something useful.
"""

import sys
import csv
import codecs
import re

from datetime import date
from typing import Dict, Any
from argparse import ArgumentParser
from collections import namedtuple
from pathlib import Path

from term_codes import term_code
from gened import gened_courses

csv.field_size_limit(sys.maxsize)

days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
rds = {'RECR': 'EC',
       'RLPR': 'LPS',
       'RMQR': 'MQR',
       'FCER': 'CE',
       'FISR': 'IS',
       'FUSR': 'USED',
       'FSWR': 'SW',
       'FWGR': 'WGCI'}

# Generate dict of GenEd courses and the requirements they satisfy
GenEd = namedtuple('GenEd', 'rd variant copt')
no_gened = GenEd._make(['', '', ''])
# gened_courses = dict()
# that = None
# # Get latest  QNS_GENED csv from downloads and say that that's that.
# them = Path().glob('./downloads/*GENED*.csv')
# for this in them:
#   if that is None or this.stat().st_mtime > that.stat().st_mtime:
#     that = this
# if that is not None:
#   print(f'Using {that.name}')
#   with open(that) as gened_file:
#     cols = None
#     reader = csv.reader(gened_file)
#     for line in reader:
#       if cols is None:
#         cols = ([col.lower().replace(' ', '_') for col in line])
#         GenEd_Row = namedtuple('GenEd_Row', cols)
#       else:
#         row = GenEd_Row._make(line)
#         course = f'{row.subject.strip()} {row.catalog.strip()}'
#         copts = [copt for copt in row.copt.split(', ') if copt.startswith('QNS')]
#         if len(copts) == 0:
#           copts = ['—']
#         gened_courses[course] = GenEd._make([row.designation, row.variant, ',@'.join(copts)])
# else:
#   print('NOTE: GenEd info missing.')


def numeric_part(catnum_str):
  """ For sorting courses in catalog number order within a discipline.
  """
  num_part = float(re.search(r'(\d+(\.\d+)?)', catnum_str).group(1))
  while num_part > 1000.0:
    num_part /= 10.0
  return f'{num_part:06.1f}'


def make_meetings_str(start, end, days_yn):
  """ Make a string that tells the days and times when a class section meets.
      Spaces are filled with @, which need to be fixed once the string has been encapsulated in
      a cell.
  """
  day_list = set()
  for i in range(len(days_yn)):
    if days_yn[i] == 'Y':
      day_list.add(i)
  dows = [days[index] for index in sorted(day_list)]
  time = (f'{start.replace(":00.000000", "").strip().lower()}-'
          f'{end.replace(":00.000000", "").strip().lower()}')
  combined = ',@'.join(dows) + f'@{time.replace(" ", "@")}'
  separate = [f'{d}@{time}' for d in dows] + ['—'] * (3 - len(dows))
  return combined, separate


def mogrify(input_file, separate_meeting_cols=False):
  """ Convert an ENROLLMENT-CAPACITY query into a useable format, including GenEd info.
  """
  input_path = Path(input_file)
  if not input_path.exists():
    raise ValueError(f'{input_path} not found.')

  courses = []
  status_counts: Dict[str, int] = dict()
  cols = None
  output_file = None

  # Force the input file to be valid utf-8 text.
  with codecs.open(input_file, 'r', encoding='utf-8', errors='replace') as infile:
    reader = csv.reader(infile)
    for line in reader:
      if cols is None:
        line[0] = line[0].replace('\ufeff', '')
        if line[0] != 'Institution':
          continue
        cols = [col.lower().replace(' ', '_') for col in line]
        if args.debug:
          print(cols, file=sys.stderr)
        Row = namedtuple('Row', cols)
      else:
        row = Row._make(line)
        # The CUNYfirst query could be used for any institution, but this is a QC project.
        if row.institution != 'QNS01':
          continue

        if output_file is None:
          # Use the query SYSDATE for the output file name
          m, d, y = (int(col) for col in row.sysdate.split('/'))
          # Have to assume 21st century
          if y < 100:
            y += 2000
          # Include Separate/Combined info in file name
          sc_info = 'separate' if separate_meeting_cols else 'combined'
          output_file = f'./archive/{y}-{int(m):02}-{int(d):02}_enrollments_{sc_info}.csv'
        semester_code, semester_name = term_code(row.term, row.session)
        if row.class_status not in status_counts.keys():
          status_counts[row.class_status] = 0
        status_counts[row.class_status] += 1
        if row.class_status != 'Active':
          continue

        course_str = f'{row.subject_area:>7}@{row.catalog_nbr.strip():<6}'
        title = row.class_title.replace(' ', '@').replace('\'', '’')
        career = row.career
        primary_component = row.primary_component
        has_fees = row.fees_exist
        is_ztc = 'Y' if row.crse_attr == 'OERS' else '—'
        section = row.class_section
        class_number = row.class_nbr
        this_component = row.course_component
        enrollment = row.enrollment_total
        limit = row.enrollment_capacity
        room = row.facility_id if row.facility_id != '' else '—'
        mode = row.instruction_mode
        combined, separate = make_meetings_str(row.mtg_start, row.mtg_end,
                                               [row.mon, row.tues, row.wed, row.thurs,
                                                row.fri, row.sat, row.sun])
        gened_key = course_str.replace('@', ' ').strip()
        if gened_key in gened_courses.keys():
          gened = gened_courses[gened_key]
        else:
          gened = no_gened

        # For spaces in the instructor’s name
        instructor_name = row.instructor.replace(',', ',@').replace(' ', '@')
        if instructor_name == '':
          instructor_name = '—'
        instructor_role = row.role.replace(',', ',@').replace(' ', '@')
        if instructor_role == '':
          instructor_role = '—'
        if separate_meeting_cols:
          courses.append(f'{semester_code} {semester_name}'
                         f' {course_str} {title} {career} {has_fees} {is_ztc} {primary_component}'
                         f' {this_component} {class_number}'
                         f' {section:>05} {enrollment:>3} {limit:>4} {room}'
                         f' "{separate[0]}" "{separate[1]}" "{separate[2]}"'
                         f' {mode} {instructor_name} {instructor_role}'
                         f' {gened.rd} {gened.variant} {gened.copt}')
        else:
          courses.append(f'{semester_code} {semester_name}'
                         f' {course_str} {title} {career} {has_fees} {is_ztc} {primary_component}'
                         f' {this_component} {class_number} {section:>05}'
                         f' {enrollment:>3} {limit:>4} {room} {combined} {mode}'
                         f' {instructor_name} {instructor_role}'
                         f' {gened.rd} {gened.variant} {gened.copt}')
  courses.sort(key=lambda course: numeric_part(course[8:14]))
  courses.sort(key=lambda course: course[0:7].strip())
  print(f'Generating {output_file}')
  with open(output_file, 'w') as outfile:
    writer = csv.writer(outfile)
    if separate_meeting_cols:
      writer.writerow(['Semester Code', 'Semester Name',
                       'Course', 'Title', 'Level', 'Has Fees', 'OERS', 'Primary Component',
                       'This Component', 'Class #', 'Section', 'Enrollment', 'Limit',
                       'Room', 'First', 'Second', 'Third', 'Mode', 'Name',
                       'Role', 'RD', 'STEM Variant', 'COPT'])
    else:
      writer.writerow(['Semester Code', 'Semester Name',
                       'Course', 'Title', 'Level', 'Has Fees', 'OERS', 'Primary Component',
                      'This Component', 'Class #', 'Section', 'Enrollment', 'Limit',
                       'Room', 'Schedule', 'Mode', 'Name', 'Role', 'RD', 'STEM Variant', 'COPT'])
    for course in courses:
      row = course.split()
      row = [col.replace('@', ' ').replace('"', '') for col in row]
      writer.writerow(row)

  for status, count in status_counts.items():
    print(f'{count:6,} {status}', file=sys.stderr)


if __name__ == '__main__':
  """ Find the latest enrollment file and process it.
  """
  parser = ArgumentParser(description='Transform CUNY enrollment query into something useful.')
  parser.add_argument('-d', '--debug', action='store_true')
  parser.add_argument('-q', '--query_file', default=None)
  parser.add_argument('-s', '--separate_meeting_columns', action='store_true')
  parser.add_argument('-sv', '--stem_variant', action='store_true')
  args = parser.parse_args()
  if args.query_file is None:
    that = None
    # Get latest csv from downloads and say that that's that.
    them = Path().glob('./downloads/QCCV_SR_CLASS_ENRL_LOC_TIME_RD*.csv')
    for this in them:
      if that is None or this.stat().st_mtime > that.stat().st_mtime:
        that = this
  else:
    that = Path(args.query_file)
  print(f'Using {that.name}')
  mogrify(that, args.separate_meeting_columns)
