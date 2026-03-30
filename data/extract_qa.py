import json

input_file = r"d:\## Workspace(model4, 0318)\data\labeled.jsonl"
output_file = r"d:\## Workspace(model4, 0318)\data\extracted_qa.jsonl"

with open(input_file, 'r', encoding='utf-8') as f_in, open(output_file, 'w', encoding='utf-8') as f_out:
    for line in f_in:
        try:
            data = json.loads(line.strip())
            question = ""
            final_answer = ""
            
            contents = data.get("contents", [])
            for content in contents:
                if content.get("role") == "user":
                    question = content["parts"][0]["text"]
                elif content.get("role") == "model":
                    text = content["parts"][0]["text"]
                    if "### [최종 답변]" in text:
                        final_answer = text.split("### [최종 답변]")[1].strip()
                    else:
                        final_answer = text.strip()
            
            out_data = {
                "question": question,
                "final_answer": final_answer
            }
            f_out.write(json.dumps(out_data, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"Error processing line: {e}")

print(f"Extraction complete. Results saved to {output_file}")
