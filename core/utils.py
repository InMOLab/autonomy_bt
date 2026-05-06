import yaml
import os
import re
import xml.etree.ElementTree as ET
import importlib


def to_snake_case(name: str) -> str:
    # 연속된 대문자 그룹을 처리해서 snake_case 변환
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
    return s2.lower()

def load_config(config_file):
    with open(config_file, 'r', encoding="utf-8") as f:
        return yaml.safe_load(f)

# Global variable to hold the configuration
config = None

def set_config(config_file):
    global config
    config = load_config(config_file)
    config['config_file_path'] = config_file

def get_file_dirname(file):
    return os.path.dirname(os.path.abspath(file))  # 모듈 파일 기준

# BT xml
def parse_behavior_tree(xml_path):
    try:
        # 1차 시도: 원래 경로
        tree = ET.parse(xml_path)
        return tree.getroot()
    except FileNotFoundError:
        # 2차 시도: 파일명을 snake_case로 바꿔서 다시 시도
        dirname, filename = os.path.split(xml_path)
        name, ext = os.path.splitext(filename)
        snake_name = to_snake_case(name)
        alt_path = os.path.join(dirname, snake_name + ext)

        try:
            tree = ET.parse(alt_path)
            return tree.getroot()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Neither '{xml_path}' nor '{alt_path}' could be found.")


def extract_agent_id(agent_or_dict):
    """Best-effort agent_id extraction from either an Agent obj or a dict."""
    if isinstance(agent_or_dict, dict):
        return agent_or_dict.get('agent_id')
    return getattr(agent_or_dict, 'agent_id', None)


def extract_task_id(task_or_dict):
    """Best-effort task_id extraction from either a Task obj or a dict."""
    if isinstance(task_or_dict, dict):
        return task_or_dict.get('task_id')
    return getattr(task_or_dict, 'task_id', None)


def convert_value(v): # "None" → None; 문자열 숫자는 숫자로 변환
    if v == "None":
        return None
    if isinstance(v, str):
        if v.isdigit() or (v.startswith('-') and v[1:].isdigit()):
            return int(v)
        try:
            return float(v)
        except ValueError:
            pass
    return v


def optional_import(name):
    if not name:
        return None
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        # 요청한 모듈 자체가 없을 때만 None 반환
        if e.name == name:
            return None
        # 내부 의존 모듈 누락 등은 그대로 올림
        raise

# For AgentBT Node
def first_action_or_condition_name(children):
    """
    children 및 그 하위(children만 사용)를 DFS로 순회하며
    type이 'Action' 또는 'Condition'인 첫 노드의 name을 반환.
    없으면 None 반환.
    """
    if not children:
        return None

    def dfs(nodes):
        for node in nodes:
            node_type = getattr(node, "type", None)
            if node_type in ("Action", "Condition"):
                name = getattr(node, "name", None)
                if name is not None:
                    return name  # 첫 유효 name 반환

            subchildren = getattr(node, "children", None)
            if subchildren:
                found = dfs(subchildren)
                if found is not None:
                    return found
        return None

    return dfs(children)
