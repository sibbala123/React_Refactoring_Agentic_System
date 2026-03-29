import os

replacements = {
    # Replace Jayan's supabase path
    r"C:\\Users\\jayan\\supabase-master": r"C:\\Users\\Admin\\Desktop\\supabase",
    r"C:\Users\jayan\supabase-master": r"C:\Users\Admin\Desktop\supabase",
    
    # Replace Jayan's repo path
    r"C:\\Users\\jayan\\7000 project\\agentic_refactor_system": r"C:\\Users\\Admin\\Desktop\\React Refactor\\agentic_refactor_system",
    r"C:\Users\jayan\7000 project\agentic_refactor_system": r"C:\Users\Admin\Desktop\React Refactor\agentic_refactor_system",
    
    # Replace D: drives
    r"D:\\Agentic\\React\\supabase": r"C:\\Users\\Admin\\Desktop\\supabase",
    r"D:\Agentic\React\supabase": r"C:\Users\Admin\Desktop\supabase",
    r"D:\\Agentic\\React_Refactoring_Agentic_System": r"C:\\Users\\Admin\\Desktop\\React Refactor",
    r"D:\Agentic\React_Refactoring_Agentic_System": r"C:\Users\Admin\Desktop\React Refactor",
}

for root, _, files in os.walk('.'):
    for filename in files:
        if filename.endswith(('.json', '.txt', '.py', '.csv', '.yaml')) and filename != 'fix_paths.py':
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue
                
            modified = content
            for old_str, new_str in replacements.items():
                modified = modified.replace(old_str, new_str)
                
            if modified != content:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(modified)
                print(f"Updated {path}")
