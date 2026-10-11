from .registry import register
import scheduler
import planner

register('schedule_once','Programa una orden para una fecha/hora ISO 8601.',lambda prompt,run_at:scheduler.add_once(prompt,run_at),{'prompt':'string','run_at':'ISO datetime'},risk='high',confirm=True)
register('schedule_interval','Programa una orden recurrente cada N segundos.',lambda prompt,seconds:scheduler.add_interval(prompt,seconds),{'prompt':'string','seconds':'number'},risk='high',confirm=True)
register('schedule_list','Lista tareas programadas.',lambda:scheduler.list_jobs(),{})
register('schedule_cancel','Cancela una tarea programada.',lambda job_id:scheduler.cancel(job_id),{'job_id':'string'},risk='high',confirm=True)
register('plan_create','Crea un plan persistente de pasos.',planner.create,{'title':'string','steps':'array'})
register('plan_list','Lista planes persistentes.',planner.list_plans,{})
register('plan_get','Obtiene un plan.',planner.get,{'plan_id':'string'})
register('plan_update','Actualiza el estado de un paso del plan.',planner.update,{'plan_id':'string','step_id':'number','status':'pending|running|done|failed','result':'any opcional'})

register('plan_execute','Ejecuta un plan persistente paso por paso y registra resultados.',planner.execute,{'plan_id':'string'},risk='high',confirm=True)
