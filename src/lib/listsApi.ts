// Lists API — self-contained tool, its own endpoints on the sidecar.

const BASE = "http://127.0.0.1:8765";

export interface ListItem {
  id: string;
  text: string;
  note: string;
  done: boolean;
}
export interface TodoList {
  id: string;
  name: string;
  items: ListItem[];
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

export async function getLists(): Promise<TodoList[]> {
  const res = await fetch(`${BASE}/lists`);
  const data = await res.json();
  return data.lists;
}
export const addList = (name: string) => post<TodoList>("/lists/add", { name });
export const renameList = (id: string, name: string) =>
  post("/lists/rename", { id, name });
export const deleteList = (id: string) => post("/lists/delete", { id });
export const addItem = (list_id: string, text: string, note: string) =>
  post<ListItem>("/lists/item/add", { list_id, text, note });
export const updateItem = (
  id: string,
  patch: { text?: string; note?: string; done?: boolean }
) => post("/lists/item/update", { id, ...patch });
export const deleteItem = (id: string) => post("/lists/item/delete", { id });
