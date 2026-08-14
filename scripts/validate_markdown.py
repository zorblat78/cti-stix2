# This script exists to validate the structure and numbering of sections in a Markdown document.
# It will return 1 if any errors appear in 0 if it succeeds
# Usage: python validate_markdown.py <markdown_file.md>

import argparse
import re
from sys import prefix
from lxml import etree

def _get_next_html_table(content: str, offset: int = 0):
    """Get the start and end indices of the first table in the content."""
    table_start = content.find("<table", offset)

    if table_start != -1:
        table_end = content.find("</table>", table_start) + len("</table>")
    else:
        table_end = -1

    return table_start, table_end

def validate_html_tables(content: str):
    """Validate that all HTML tables in the document are well-formed."""
    errors = []
    table_start, table_end = _get_next_html_table(content)
    doc_sections = []
    parser = etree.XMLParser(resolve_entities=False, no_network=True)

    for match in re.finditer(r'\n\#+([^<\n\r]+)', content, re.MULTILINE):
        doc_sections.append((match.start(), match.group(1).strip()))


    current_section = doc_sections.pop(0)
    table_in_section = 1
    while table_start != -1 and table_end != -1:
        # this gives us a better reference to find the table in the error
        while len(doc_sections) > 0 and table_start > doc_sections[0][0]:
            table_in_section = 1
            current_section = doc_sections.pop(0)

        # replace &nbsp; with a space so that the parser doesn't choke on it while still giving us harder validation rules than the HTML parser
        eval_section = content[table_start:table_end].replace("&nbsp;", " ")

        try:
            etree.fromstring(eval_section.strip(), parser=parser)
        except etree.XMLSyntaxError as e:
            errors.append(f"Failed to parse HTML for table {table_in_section} in section {current_section[1]}: {e}")

        table_in_section += 1

        table_start, table_end = _get_next_html_table(content, offset=table_end)

    return errors

def validate_section_numbers(content: str):
    """Check heading numbering, indentation depth, and ordering in the document."""
    pattern = re.compile(r'\n(#+) (\d+(\.\d+)*)\.? +([^<\n]+)')
    results = pattern.findall(content, re.MULTILINE)
    errors = []
    running_counts = []
    last_name = ''

    for result in results:
        depth = len(result[0])
        number = result[1]
        name = result[3]

        if depth > len(running_counts):
            running_counts.append(0)
            last_name = ""
        elif depth < len(running_counts):
            running_counts = running_counts[:depth]
            last_name = ""
        else:
            name = name.strip()
            # section 1 and 12 don't follow alphabetical order currently.  Section 1 and 3 for narrative reasons.  Sections 9 and 12 are for legacy ones.
            # 7.2.3 is for granular markings which are after object markings so this also might make sense from a narrative perspective
            if last_name > name and running_counts[0] not in (1, 3, 9, 12) and number != "7.2.3":
                errors.append(f"Section {number} contains {name} which should appear before {last_name}")
            last_name = name

        running_counts[-1] += 1
        expected_num = ".".join(str(count) for count in running_counts)
        if expected_num != number:
            errors.append(f"Section number mismatch for section: {number} expected {expected_num}")

        if depth != len(number.split('.')):
            errors.append(f"Indentation mismatch for section number: {number}")

    return errors

def validate_references(content: str):
    """Validate that markdown and HTML links point to existing anchors."""
    valid_anchors = set()
    anchors = re.findall(r'<a id=[\'"]([^"\']*)["\']', content, re.MULTILINE)
    markdown_references = re.findall(r'\(#([^)]+)\)', content, re.MULTILINE)
    html_references = re.findall(r'href=[\'"]#([^"\']+)["\']', content, re.MULTILINE)

    for anchor in anchors:
        valid_anchors.add(anchor)

    errors = set()
    for reference in markdown_references:
        if reference not in valid_anchors:
            errors.add(f"Invalid reference: {reference}")
    for reference in html_references:
        if reference not in valid_anchors:
            errors.add(f"Invalid reference: {reference}")

    return list(errors)

def validate_table_of_contents(content: str):
    """Verify that the table of contents matches the document headings."""
    errors = []
    table_start = content.find('# Table of Contents')
    table_end = content.find('---', table_start + 1)
    full_table = content[table_start: table_end]
    table_entries = re.findall(r'- ([\dA-Z]+(\.\d+)*|Appendix [A-Z])[:\.]? +\[([^\]]+)\]\(#([^)]+)\)', full_table)
    all_sections = re.findall(r'\n#+ ([\dA-Z]+(\.\d+)*|Appendix [A-Z])[:\.]? +([^<\n]+)<a id=[\'"]([^"\']*)["\']>', content[table_end:], re.MULTILINE)

    table_dict = {}
    actual_entries = set()
    
    for entry in table_entries:
        if entry[0]:
            table_dict[entry[0]] = {
                "title": entry[2].strip(),
                "anchor": entry[3].strip()
            }

    for entry in all_sections:
        actual_entries.add(entry[0])
        if entry[0] not in table_dict:
            errors.append(f"Section {entry[0]} is in the document but not in the table of contents.")
        elif table_dict[entry[0]]["title"] != entry[2].strip():
            errors.append(f"Title mismatch for section {entry[0]}: expected '{table_dict[entry[0]]['title']}', got '{entry[2].strip()}'")
        elif table_dict[entry[0]]["anchor"] != entry[3].strip():
            errors.append(f"Anchor mismatch for section {entry[0]}: expected '{table_dict[entry[0]]['anchor']}', got '{entry[3].strip()}'")

    for entry in table_dict.keys():
        if entry not in actual_entries:
            errors.append(f"Section {entry} is in the table of contents but not in the document.")

    return errors

def validate_relationships(content: str):
    """Validate that all forward and reverse relationships in the document match each other and that they are aggregated up in the end."""
    errors = []
    forward_relationships = {}
    reverse_relationships = {}
    
    name_pattern = re.compile(r'#+ (?:\d+(?:\.\d+)*)\.? Relationships <a id=[\'"]([^"\']+)-relationships["\']>', re.MULTILINE)   

    for name_match in name_pattern.finditer(content):
        name = name_match.group(1)
        end = min(content.find("\n#", name_match.end()), content.find("\n*", name_match.end()))
        relationship_section = content[name_match.end():end]

        table_start, table_end = _get_next_html_table(relationship_section)
        table_count = 0

        while table_start != -1 and table_end != -1:            
            table_count += 1
            if relationship_section[table_start:table_end].find("Embedded Relationships") != -1 or relationship_section[table_start:table_end].find("Common Relationships") != -1:
                table_start, table_end = _get_next_html_table(relationship_section, table_end)
                continue

            try:
                html = etree.fromstring(relationship_section[table_start:table_end].strip())
            except etree.XMLSyntaxError as e:
                errors.append(f"Failed to parse HTML for table {table_count} in relationship section for {name}: {e}")
                table_start, table_end = _get_next_html_table(relationship_section, table_end)
                continue
            
            if html is None:
                errors.append(f"Failed to parse HTML for table {table_count} in relationship section")
                table_start, table_end = _get_next_html_table(relationship_section, table_end)
                continue

            dictionary = forward_relationships
            if relationship_section[table_start:table_end].find("Reverse Relationships") != -1:
                dictionary = reverse_relationships

            table_start, table_end = _get_next_html_table(relationship_section, table_end)

            for row in html.xpath("/table/tr/td/.."):
                sources = row.xpath("td[1]/*[self::a or self::span]/text()")
                relationship_type = row.xpath("td[2]/span/text()")
                targets = row.xpath("td[3]/*[self::a or self::span]/text()")
                for source in sources:
                    for target in targets:
                        dictionary.setdefault(source, {}).setdefault(relationship_type[0], set()).add(target)

    
    return errors

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Validates Markdown Document')
    parser.add_argument("file", help="Path to the Markdown file to validate")
    args = parser.parse_args()
    errors = []

    with open(args.file, 'r', encoding='utf-8') as input_file:
        content = input_file.read()

    errors.extend(validate_html_tables(content))
    errors.extend(validate_section_numbers(content))
    errors.extend(validate_references(content))
    errors.extend(validate_table_of_contents(content))
    errors.extend(validate_relationships(content))

    if len(errors) > 0:
        for error in errors:
            print("\033[91m" + error + "\033[0m")
        exit(1)

    print("\033[92mNo errors found\033[0m")
    exit(0)