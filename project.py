import json
import os


class Project:
    def __init__(self):
        self.folder = ""
        self.name = "Untitled"
        self.sources = []
        self.bookmarks = []
        self.frame_data = {}
        self.settings = {
            'fps': 24,
            'loop': False
        }
    
    def add_source(self, folder, sequence_info):
        source = {
            'folder': folder,
            'name': sequence_info.get('name', 'Sequence'),
            'files': sequence_info.get('files', []),
            'start': sequence_info.get('start', 0),
            'end': sequence_info.get('end', len(sequence_info.get('files', [])) - 1),
            'relative_path': os.path.relpath(folder, os.path.dirname(folder))
        }
        self.sources.append(source)
    
    def set_current_frame(self, frame):
        self.current_frame = frame
    
    def add_bookmark(self, frame, name="", color="#ff6b35"):
        bookmark = {
            'frame': frame,
            'name': name,
            'color': color,
            'annotations': []
        }
        self.bookmarks.append(bookmark)
        return bookmark
    
    def remove_bookmark(self, frame):
        self.bookmarks = [b for b in self.bookmarks if b['frame'] != frame]
    
    def get_bookmark(self, frame):
        for b in self.bookmarks:
            if b['frame'] == frame:
                return b
        return None
    
    def set_frame_data(self, frame, **kwargs):
        if frame not in self.frame_data:
            self.frame_data[frame] = {}
        self.frame_data[frame].update(kwargs)
    
    def get_frame_data(self, frame):
        return self.frame_data.get(frame, {})
    
    def save(self, filepath):
        project_data = {
            'version': '1.0',
            'name': self.name,
            'sources': [],
            'bookmarks': self.bookmarks,
            'frame_data': self.frame_data,
            'settings': self.settings
        }
        
        for source in self.sources:
            project_data['sources'].append({
                'path': source.get('relative_path', source.get('folder', '')),
                'absolute': source.get('folder', ''),
                'name': source.get('name', ''),
                'start': source.get('start', 0),
                'end': source.get('end', 0)
            })
        
        with open(filepath, 'w') as f:
            json.dump(project_data, f, indent=2)
    
    def load(self, filepath):
        with open(filepath, 'r') as f:
            project_data = json.load(f)
        
        self.name = project_data.get('name', 'Untitled')
        self.bookmarks = project_data.get('bookmarks', [])
        self.frame_data = project_data.get('frame_data', {})
        self.settings = project_data.get('settings', {'fps': 24, 'loop': False})
        
        self.sources = []
        for source_data in project_data.get('sources', []):
            if os.path.exists(source_data.get('absolute', '')):
                self.add_source(source_data['absolute'], {
                    'name': source_data.get('name', 'Sequence'),
                    'files': [],
                    'start': source_data.get('start', 0),
                    'end': source_data.get('end', 0)
                })
