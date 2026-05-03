import os

path = r"C:\Users\Matt\Documents\GitHub\skills\ts-large-file-refactor\test_data\Dashboard.tsx"

content = []
content.append("import React, { useState, useEffect } from 'react';\n\n")

# Generate lots of types
content.append("// --- TYPES ---\n")
for i in range(80):
    content.append(f"export interface DashboardWidget{i} {{\n  id: string;\n  title: string;\n  data: any;\n  isVisible: boolean;\n}}\n")

content.append("export interface DashboardProps {\n  userId: string;\n}\n\n")

# Generate lots of constants
content.append("// --- CONSTANTS ---\n")
for i in range(150):
    content.append(f"const WIDGET_DEFAULT_TITLE_{i} = 'Default Title {i}';\n")
    content.append(f"const WIDGET_ENDPOINT_{i} = 'https://api.example.com/v1/widget/{i}';\n")

content.append("\n// --- HELPERS ---\n")
# Generate helper functions
for i in range(40):
    content.append(f"const formatData{i} = (data: any) => {{ return data ? data.toString() + ' formatted' : 'N/A'; }};\n")

content.append("\n// --- COMPONENT ---\n")
# Generate React Component
content.append("export const Dashboard: React.FC<DashboardProps> = ({ userId }) => {\n")
for i in range(50):
    content.append(f"  const [widget{i}Data, setWidget{i}Data] = useState<any>(null);\n")

content.append("\n  useEffect(() => {\n")
content.append("    // Fetch data for all widgets\n")
for i in range(50):
    content.append(f"    fetch(WIDGET_ENDPOINT_{i}).then(res => res.json()).then(data => setWidget{i}Data(data));\n")
content.append("  }, [userId]);\n\n")

content.append("  return (\n    <div className='dashboard-container'>\n      <h1>User Dashboard</h1>\n      <p>Welcome back to your personalized dashboard. Here you can find all your metrics.</p>\n      <div className='widget-grid'>\n")

for i in range(150):
    content.append(f"        <div className='widget-card' id='widget-{i}'>\n")
    content.append(f"          <h2>{{WIDGET_DEFAULT_TITLE_{i}}}</h2>\n")
    content.append(f"          <p>This is a hardcoded description for widget {i}. It explains what this widget does and how to use it.</p>\n")
    if i < 50:
        content.append(f"          <div className='widget-content'>{{widget{i}Data ? formatData{i}(widget{i}Data) : 'Loading...'}}</div>\n")
    else:
        content.append(f"          <div className='widget-content'>Static Content {i}</div>\n")
    content.append(f"          <button>Update Widget {i}</button>\n")
    content.append(f"        </div>\n")

content.append("      </div>\n    </div>\n  );\n};\n")

with open(path, "w", encoding="utf-8") as f:
    f.writelines(content)

print(f"Generated {len(content)} statements/blocks resulting in a file with approx {sum(c.count(chr(10)) for c in content)} lines.")
