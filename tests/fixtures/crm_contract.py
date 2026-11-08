"""Synthetic typed CRM. Uses only temporary tool-owned SQLite data in tests."""
import json

BACKEND = '''from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException

class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    stage: str = Field(default='New', max_length=40)

class Customer(CustomerInput):
    id: int

class FollowupInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str = Field(min_length=1, max_length=200)

class Followup(FollowupInput):
    id: int
    customer_id: int

class CustomerDetail(Customer):
    followups: list[Followup]

class Deleted(BaseModel):
    deleted: bool

def setup(app, sdk):
    database = sdk.data_dir / 'crm.sqlite'
    @contextmanager
    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, stage TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS followups (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), note TEXT NOT NULL)')

    @app.get('/api/customers', operation_id='list_customers', response_model=list[Customer])
    def list_customers(q: str = ''):
        with connect() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM customers WHERE name LIKE ? ORDER BY id', ('%' + q + '%',))]

    @app.post('/api/customers', operation_id='create_customer', response_model=Customer)
    def create_customer(payload: CustomerInput):
        with connect() as connection:
            cursor = connection.execute('INSERT INTO customers(name, stage) VALUES (?, ?)', (payload.name, payload.stage))
            return {'id': cursor.lastrowid, **payload.model_dump()}

    @app.put('/api/customers/{customer_id}', operation_id='edit_customer', response_model=Customer)
    def edit_customer(customer_id: int, payload: CustomerInput):
        with connect() as connection:
            cursor = connection.execute('UPDATE customers SET name=?, stage=? WHERE id=?', (payload.name, payload.stage, customer_id))
            if not cursor.rowcount:
                raise HTTPException(404, 'Customer missing')
            return {'id': customer_id, **payload.model_dump()}

    @app.get('/api/customers/{customer_id}', operation_id='customer_detail', response_model=CustomerDetail)
    def customer_detail(customer_id: int):
        with connect() as connection:
            row = connection.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'Customer missing')
            notes = [dict(item) for item in connection.execute('SELECT * FROM followups WHERE customer_id=? ORDER BY id', (customer_id,))]
            return {**dict(row), 'followups': notes}

    @app.post('/api/customers/{customer_id}/followups', operation_id='add_followup', response_model=Followup)
    def add_followup(customer_id: int, payload: FollowupInput):
        with connect() as connection:
            if not connection.execute('SELECT id FROM customers WHERE id=?', (customer_id,)).fetchone():
                raise HTTPException(404, 'Customer missing')
            cursor = connection.execute('INSERT INTO followups(customer_id, note) VALUES (?, ?)', (customer_id, payload.note))
            return {'id': cursor.lastrowid, 'customer_id': customer_id, **payload.model_dump()}

    @app.delete('/api/customers/{customer_id}', operation_id='delete_customer', response_model=Deleted)
    def delete_customer(customer_id: int):
        with connect() as connection:
            connection.execute('DELETE FROM followups WHERE customer_id=?', (customer_id,))
            connection.execute('DELETE FROM customers WHERE id=?', (customer_id,))
            return {'deleted': True}
'''

FRONTEND = '''
import {useEffect,useState} from 'react'
import {Alert,Button,Card,Input,Space,Table,Typography} from 'antd'
import {api,type Customer,type CustomerDetail} from '@calabash/api'
export default function App(){
 const [customers,setCustomers]=useState<Customer[]>([]),[current,setCurrent]=useState<CustomerDetail|null>(null)
 const [name,setName]=useState(''),[query,setQuery]=useState(''),[note,setNote]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
 async function perform(action:()=>Promise<void>){if(busy)return;setBusy(true);setError('');try{await action()}catch{setError('Please retry')}finally{setBusy(false)}}
 async function load(){setCustomers(await api.list_customers({query:{q:query}}))}
 async function select(id:number){const customer=await api.customer_detail({params:{customer_id:id}});setCurrent(customer);setName(customer.name)}
 async function create(){const saved=await api.create_customer({body:{name}});await load();await select(saved.id)}
 async function save(){if(!current)return;await api.edit_customer({params:{customer_id:current.id},body:{name,stage:'Contacted'}});await load();await select(current.id)}
 async function followup(){if(!current)return;await api.add_followup({params:{customer_id:current.id},body:{note}});setNote('');await select(current.id)}
 useEffect(()=>{let active=true;void api.list_customers({query:{q:''}}).then(rows=>{if(active)setCustomers(rows)}).catch(()=>{if(active)setError('Please retry')});return()=>{active=false}},[])
 return <main style={{padding:24,maxWidth:960,margin:'auto',display:'grid',gap:16}}><Typography.Title level={2}>Customer workspace</Typography.Title>{error&&<Alert type="error" title={error}/>}
 <Space><Input value={query} placeholder="Filter customers" onChange={e=>setQuery(e.target.value)}/><Button loading={busy} onClick={()=>void perform(load)}>Search</Button></Space>
 <Table<Customer> rowKey="id" dataSource={customers} columns={[{title:'Customer',dataIndex:'name'},{title:'Stage',dataIndex:'stage'}]} onRow={row=>({onClick:()=>void perform(()=>select(row.id))})}/>
 <Card title={current?'Customer detail':'New customer'}><Space orientation="vertical"><Input value={name} placeholder="Customer name" onChange={e=>setName(e.target.value)}/><Space><Button disabled={busy||!name} onClick={()=>void perform(create)}>Add customer</Button><Button disabled={busy||!current||!name} onClick={()=>void perform(save)}>Save changes</Button></Space>
 {current&&<><h3>Follow-ups</h3><ul>{current.followups.map(item=><li key={item.id}>{item.note}</li>)}</ul><Input value={note} placeholder="Follow-up note" onChange={e=>setNote(e.target.value)}/><Button disabled={busy||!note} onClick={()=>void perform(followup)}>Add follow-up</Button></>}
 </Space></Card></main>
}
'''



def fixture():
    return {'tool.json': json.dumps({'format': 'calabash-react-tool', 'version': 1, 'project': 'demo', 'name': 'crm_contract', 'title': 'Synthetic CRM'}),
            'backend/main.py': BACKEND, 'frontend/App.tsx': FRONTEND}
