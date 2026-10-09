"""Prepare the dedicated local task-0 fixture via Django shell; no credentials."""
from application.models import Application
from tools.models import Tool

app = Application.objects.get(name="任务0只读工具工作流")
tool = Tool.objects.get(name="task0_public_project_info")
flow = app.work_flow
assert not flow["edges"], "Refuse to overwrite an already configured workflow"
for node in flow["nodes"]:
    node["x"] = 250 if node["id"] == "base-node" else 700
    node["y"] = 450
flow["nodes"].append({
    "id": "task0-readonly-tool", "type": "tool-node", "x": 1150, "y": 450,
    "properties": {"stepName": "只读公开资料工具", "showNode": True,
                   "config": {"fields": [{"label": "结果", "value": "result"}]},
                   "node_data": {"input_field_list": [], "code": tool.code, "is_result": True}},
})
flow["edges"].append({
    "id": "task0-start-to-tool", "type": "app-edge",
    "sourceNodeId": "start-node", "targetNodeId": "task0-readonly-tool",
    "sourceAnchorId": "start-node_right", "targetAnchorId": "task0-readonly-tool_left",
    "startPoint": {"x": 860, "y": 450}, "endPoint": {"x": 990, "y": 450},
    "properties": {},
    "pointsList": [{"x": 860, "y": 450}, {"x": 900, "y": 450},
                   {"x": 950, "y": 450}, {"x": 990, "y": 450}],
})
app.save(update_fields=["work_flow"])
print("Prepared task-0 workflow", app.id)
