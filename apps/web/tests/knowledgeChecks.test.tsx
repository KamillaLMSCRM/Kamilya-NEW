import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Learner from '@/features/knowledge-checks/Learner';
import Author from '@/features/knowledge-checks/Author';

const mocked = vi.hoisted(() => ({ request: vi.fn(), identity: vi.fn(() => 'scope') }));
vi.mock('@/features/knowledge-checks/transport', () => ({ base:'/v1/knowledge-checks', request:mocked.request, identity:mocked.identity, requestError:()=>({text:'Failed',uncertain:true}) }));
vi.mock('@/i18n/useT', () => ({useT:()=>({lang:'en'})}));
vi.mock('@/store/authStore', () => ({useAuthStore:()=>({user:{user_id:'user',tenant_id:'tenant',role:'student'},accessToken:'token',sessionEpoch:1})}));
const assignment={id:'a',check_id:'c',title:'Safety',revision:1,due_at:null,status:'in_progress',attempt_limit:2,attempts_count:1,score_percent:null,passed:false,attempts:[{id:'t',status:'started',number:1}]};
const attempt={id:'t',assignment_id:'a',number:1,status:'started',started_at:'2026-01-01',deadline_at:null,completed_at:null,score_percent:null,passed:null,earned_points:null,total_points:null,answers:[{question_id:'q',selected_choice_ids:['one']}],snapshot:{title:'Safety',instructions:'Choose',questions:[{id:'q',text:'Question?',type:'MCQ',points:1,choices:[{id:'one',text:'One'},{id:'two',text:'Two'}]}]}};
describe('standalone knowledge checks learner',()=>{
  beforeEach(()=>{mocked.request.mockReset();mocked.identity.mockReturnValue('scope');});
  it('restores saved answers on reload and saves selected_choice_ids',async()=>{
    mocked.request.mockImplementation((path:string, options:{method?:string})=>options.method==='PUT'?Promise.resolve({...attempt,answers:[{question_id:'q',selected_choice_ids:['two']}]}):Promise.resolve(path.endsWith('/assignments/a')?assignment:attempt));
    render(<Learner assignmentId="a"/>);
    expect(await screen.findByRole('radio',{name:'One'})).toBeChecked();
    fireEvent.click(screen.getByRole('radio',{name:'Two'}));fireEvent.click(screen.getByRole('button',{name:'Save answers'}));
    await waitFor(()=>expect(mocked.request).toHaveBeenCalledWith('/v1/knowledge-checks/attempts/t/answers',expect.objectContaining({method:'PUT',data:{answers:[{question_id:'q',selected_choice_ids:['two']}]}})));
  });
  it('changes choice order on a new attempt and restores it with the selected answer on reload', async () => {
    let active = attempt;
    mocked.request.mockImplementation((path: string) => Promise.resolve(
      path.endsWith('/assignments/a')
        ? { ...assignment, attempts: [{ id: active.id, status: 'started', number: active.number }] }
        : active,
    ));
    const labels = () => screen.getAllByRole('radio').map(input => input.parentElement?.textContent);
    const first = render(<Learner assignmentId="a"/>);
    expect(await screen.findByRole('radio', {name: 'One'})).toBeChecked();
    const initialOrder = labels();
    first.unmount();

    active = { ...attempt, id: 'retry', number: 2 };
    const second = render(<Learner assignmentId="a"/>);
    expect(await screen.findByRole('radio', {name: 'One'})).toBeChecked();
    const nextOrder = labels();
    expect(nextOrder).toEqual([...initialOrder].reverse());
    second.unmount();

    render(<Learner assignmentId="a"/>);
    expect(await screen.findByRole('radio', {name: 'One'})).toBeChecked();
    expect(labels()).toEqual(nextOrder);
  });

  it('ignores a response after the session changes',async()=>{
    let resolve!: (value: unknown)=>void; mocked.request.mockReturnValue(new Promise(r=>{resolve=r;}));
    render(<Learner/>);mocked.identity.mockReturnValue('other');resolve({items:[assignment],has_more:false});
    await waitFor(()=>expect(screen.queryByText('Safety')).not.toBeInTheDocument());
  });
  it('blocks repeat submit when the response is lost until state is refreshed',async()=>{
    vi.spyOn(window,'confirm').mockReturnValue(true);
    mocked.request.mockImplementation((path:string, options:{method?:string})=>options.method==='POST'?Promise.reject(new Error('offline')):Promise.resolve(path.endsWith('/assignments/a')?assignment:attempt));
    render(<Learner assignmentId="a"/>); await screen.findByRole('radio',{name:'One'});
    fireEvent.click(screen.getByRole('button',{name:'Submit'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Outcome unknown');
    expect(screen.getByRole('button',{name:'Submit'})).toBeDisabled();
    expect(mocked.request.mock.calls.filter(call=>call[1].method==='POST')).toHaveLength(1);
    vi.restoreAllMocks();
  });
  it('creates an MCQ with stable question and choice identifiers',async()=>{
    mocked.request.mockImplementation((path:string, options:{method?:string;data?:object})=>options.method==='POST'?Promise.resolve({...options.data,revision:1,status:'draft'}):Promise.resolve({items:[],has_more:false}));
    render(<Author/>);fireEvent.click(await screen.findByRole('button',{name:'Create'}));
    fireEvent.change(screen.getByLabelText('Title'),{target:{value:'Safety'}});
    fireEvent.change(screen.getByLabelText('Question'),{target:{value:'Which?'}});
    fireEvent.change(screen.getByLabelText('Choice 1'),{target:{value:'Yes'}});
    fireEvent.change(screen.getByLabelText('Choice 2'),{target:{value:'No'}});
    fireEvent.click(screen.getByRole('button',{name:'Save'}));
    await waitFor(()=>expect(mocked.request).toHaveBeenCalledWith('/v1/knowledge-checks/',expect.objectContaining({method:'POST',data:expect.objectContaining({title:'Safety',id:expect.any(String),questions:[expect.objectContaining({id:expect.any(String),type:'MCQ',choices:[expect.objectContaining({id:expect.any(String),is_correct:true}),expect.objectContaining({id:expect.any(String),is_correct:false})]})]})})));
  });
  it('uses the paginated student roster and excludes ineligible roles and statuses', async () => {
    const check = { id:'check', title:'Published', status:'published', revision:1, instructions:'', pass_score:70, attempt_limit:1, time_limit_minutes:null, questions:[] };
    const user = { id:'student', first_name:'A', last_name:'Learner', email:null, personnel_number:null, role:'student', is_active:true, status:'active' };
    mocked.request.mockImplementation((path:string) => {
      if (path.endsWith('/knowledge-checks/')) return Promise.resolve({items:[check],has_more:false});
      if (path === '/v1/users') return Promise.resolve({users:[user,{...user,id:'admin',last_name:'Admin',role:'admin'},{...user,id:'inactive',last_name:'Inactive',status:'inactive'}],total:3,page:1,per_page:20});
      return Promise.resolve(check);
    });
    render(<Author/>);
    fireEvent.click(await screen.findByRole('button',{name:'Open'}));
    expect(await screen.findByLabelText('Learner A')).toBeInTheDocument();
    expect(screen.queryByText('Admin A')).not.toBeInTheDocument();
    expect(screen.queryByText('Inactive A')).not.toBeInTheDocument();
    expect(mocked.request).toHaveBeenCalledWith('/v1/users',expect.objectContaining({params:{role:'student',is_active:true,page:1,per_page:20,search:undefined}}));
  });
  it('fails closed when the roster omits employee status', async () => {
    const check = { id:'check', title:'Published', status:'published', revision:1, instructions:'', pass_score:70, attempt_limit:1, time_limit_minutes:null, questions:[] };
    mocked.request.mockImplementation((path:string) => path.endsWith('/knowledge-checks/')
      ? Promise.resolve({items:[check],has_more:false})
      : path === '/v1/users'
        ? Promise.resolve({users:[{id:'student',first_name:'A',last_name:'Learner',role:'student',is_active:true}],total:1,page:1,per_page:20})
        : Promise.resolve(check));
    render(<Author/>); fireEvent.click(await screen.findByRole('button',{name:'Open'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed');
    expect(screen.queryByLabelText('Learner A')).not.toBeInTheDocument();
  });
  it('does not apply a prior check roster after switching checks', async () => {
    const common = { status:'published', revision:1, instructions:'', pass_score:70, attempt_limit:1, time_limit_minutes:null, questions:[] };
    const first = {...common,id:'one',title:'First'}; const second = {...common,id:'two',title:'Second'};
    let resolveFirst!: (value:unknown) => void; let rosterCalls = 0;
    mocked.request.mockImplementation((path:string) => {
      if (path.endsWith('/knowledge-checks/')) return Promise.resolve({items:[first,second],has_more:false});
      if (path === '/v1/users') return ++rosterCalls === 1 ? new Promise(resolve => {resolveFirst=resolve;}) : Promise.resolve({users:[],total:0,page:1,per_page:20});
      return Promise.resolve(path.endsWith('/one')?first:second);
    });
    render(<Author/>); const openButtons=await screen.findAllByRole('button',{name:'Open'});
    fireEvent.click(openButtons[0]); await waitFor(()=>expect(rosterCalls).toBe(1));
    fireEvent.click(openButtons[1]); await waitFor(()=>expect(rosterCalls).toBe(2));
    resolveFirst({users:[{id:'old',first_name:'Old',last_name:'User',role:'student',is_active:true,status:'active'}],total:1,page:1,per_page:20});
    await waitFor(()=>expect(screen.queryByText('User Old')).not.toBeInTheDocument());
  });
  it('clears selected employees, search and due date when opening another check', async () => {
    const common = {status:'published',revision:1,instructions:'',pass_score:70,attempt_limit:1,time_limit_minutes:null,questions:[]};
    const first={...common,id:'one',title:'First'}, second={...common,id:'two',title:'Second'};
    const employee={id:'student',first_name:'A',last_name:'Learner',email:null,personnel_number:null,role:'student',is_active:true,status:'active'};
    mocked.request.mockImplementation((path:string) => path.endsWith('/knowledge-checks/')
      ? Promise.resolve({items:[first,second],has_more:false})
      : path === '/v1/users' ? Promise.resolve({users:[employee],total:1,page:1,per_page:20})
        : Promise.resolve(path.endsWith('/one') ? first : second));
    render(<Author/>); const buttons=await screen.findAllByRole('button',{name:'Open'});
    fireEvent.click(buttons[0]); fireEvent.click(await screen.findByLabelText('Learner A'));
    fireEvent.change(screen.getByLabelText('Search employees'),{target:{value:'Learner'}});
    fireEvent.change(screen.getByLabelText('Due date (optional)'),{target:{value:'2027-01-01T12:00'}});
    fireEvent.click(buttons[1]);
    await waitFor(()=>expect(screen.getByLabelText('Search employees')).toHaveValue(''));
    expect(screen.getByLabelText('Due date (optional)')).toHaveValue('');
    expect(screen.getByText('Active employees · Selected: 0')).toBeInTheDocument();
  });
  it('keeps an unsaved draft when discard is cancelled', async () => {
    vi.spyOn(window,'confirm').mockReturnValue(false);
    mocked.request.mockResolvedValue({items:[],has_more:false});
    render(<Author/>);
    fireEvent.click(await screen.findByRole('button',{name:'Create'}));
    fireEvent.change(screen.getByLabelText('Title'),{target:{value:'My draft'}});
    fireEvent.click(screen.getAllByRole('button',{name:'Create'})[0]);
    expect(window.confirm).toHaveBeenCalled();
    expect(screen.getByLabelText('Title')).toHaveValue('My draft');
    vi.restoreAllMocks();
  });
  it('preserves keys when changing type and asks before dropping choices', async () => {
    vi.spyOn(window,'confirm').mockReturnValue(false);
    mocked.request.mockResolvedValue({items:[],has_more:false});
    render(<Author/>);fireEvent.click(await screen.findByRole('button',{name:'Create'}));
    const type = screen.getByLabelText('Question type');
    fireEvent.change(type,{target:{value:'multiple_choice'}});
    const correct = screen.getAllByRole('checkbox',{name:'Correct'});
    expect(correct[0]).toBeChecked(); fireEvent.click(correct[1]);
    fireEvent.change(type,{target:{value:'MCQ'}});
    fireEvent.change(type,{target:{value:'multiple_choice'}});
    expect(screen.getAllByRole('checkbox',{name:'Correct'})[0]).toBeChecked();
    expect(screen.getAllByRole('checkbox',{name:'Correct'})[1]).toBeChecked();
    fireEvent.click(screen.getByRole('button',{name:'Add choice'}));
    fireEvent.change(screen.getByLabelText('Choice 3'),{target:{value:'Keep me'}});
    fireEvent.change(type,{target:{value:'true_false'}});
    expect(window.confirm).toHaveBeenCalled();
    expect(type).toHaveValue('multiple_choice');
    expect(screen.getByLabelText('Choice 3')).toHaveValue('Keep me');
    vi.restoreAllMocks();
  });
});
