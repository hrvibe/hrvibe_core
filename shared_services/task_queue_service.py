import asyncio
import logging
from typing import Callable, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
#Создает класс Task, который представляет задачу для выполнения в очереди
class Task:
    """Объект класса Task создается с помощью конструктора __init__ и
    упаковывает функцию и её аргументы для передачи через очередь
    по сути это контейнер для функции и её аргументов
    Задача для выполнения в очереди"""
    # Функция для выполнения (async или sync)
    func: Callable
    # (arguments) — позиционные аргументы: передаются по порядку, без имен
    args: tuple = ()
    # (keyword arguments) — именованные аргументы: передаются по именам параметров
    kwargs: dict = None
    task_id: Optional[str] = None
    
    #Вызывается после инициализации объекта и инициализирует kwargs, если они не были переданы
    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}


class TaskQueue:
    """Класс который объединяет очередь задач и воркер для их обработки.
    Очереди задач с лимитом 200 и приоритизацией FIFO"""
    
    def __init__(self, maxsize: int = 200):
        """
        Инициализация объекта очереди задач
        Args:
            maxsize: Максимальный размер очереди (по умолчанию 200)
        """
        # Создает асинхронную очередь с максимальным размером maxsize
        self._queue = asyncio.Queue(maxsize=maxsize)
        # Флаг состояния воркера, по умолчанию воркер не запущен
        self._worker_running = False
        # это не задачи из очереди, а сама задача (asyncio.Task), которая представляет запущенный процесс воркера.
        self._worker_task: Optional[asyncio.Task] = None
    

    async def put(self, func: Callable, *args, task_id: Optional[str] = None, **kwargs) -> bool:
        """
        Используется для критичных задач, которые Должны быть добавлены в очередь.
        Добавить задачу в очередь.
        Если очередь заполнена, метод блокируется до тех пор, пока не освободится место.
        Args:
            func: Функция для выполнения (может быть async или sync)
            *args: Позиционные аргументы для функции
            task_id: Опциональный идентификатор задачи
            **kwargs: Именованные аргументы для функции
        
        Returns:
            bool: Всегда возвращает True (метод блокируется до добавления задачи)
        """
        # Создает объект Task, который представляет задачу для выполнения в очереди
        task = Task(func=func, args=args, kwargs=kwargs, task_id=task_id)
        # Ожидание освобождения места, если очередь заполнена, если очередь не заполнена, то задача добавляется в очередь
        # await self._queue.put() блокируется и ждет, если очередь заполнена, поэтому QueueFull не выбрасывается
        await self._queue.put(task)
        # Логирование добавления задачи в очередь
        logger.debug(f"Task {task_id or 'without ID'} added to queue. Queue size: {self._queue.qsize()}")
        # Возвращает True, если задача успешно добавлена
        return True
    

    async def put_nowait(self, func: Callable, *args, task_id: Optional[str] = None, **kwargs) -> bool:
        """
        Используется для некритичных задач, которые Можно Пропустить, если очередь.
        Добавить задачу в очередь если есть место и не нужно ждать освобождения места (non-blocking)
        Если очередь заполнена, метод не блокируется и возвращает False, задача не добавляется в очередь.
        Args:
            func: Функция для выполнения
            *args: Позиционные аргументы для функции
            task_id: Опциональный идентификатор задачи
            **kwargs: Именованные аргументы для функции
        Returns:
            bool: True если задача успешно добавлена, False если очередь переполнена
        """
        task = Task(func=func, args=args, kwargs=kwargs, task_id=task_id)
        try:
            self._queue.put_nowait(task)
            logger.debug(f"Task {task_id or 'without ID'} added to queue (nowait). Queue size: {self._queue.qsize()}")
            return True
        except asyncio.QueueFull:
            logger.warning(f"Queue is full. Task {task_id or 'without ID'} not added.")
            return False
    

    def qsize(self) -> int:
        """Получить текущий размер очереди"""
        return self._queue.qsize()
    

    def is_full(self) -> bool:
        """Проверить, заполнена ли очередь"""
        return self._queue.full()
    

    def is_empty(self) -> bool:
        """Проверить, пуста ли очередь"""
        return self._queue.empty()
    

    async def _execute_task(self, task: Task) -> Any:
        """
        Выполняет задачу используя event loop или executor в зависимости от типа функции.

        Event Loop — это нативный Python диспетчер задач для АСИНХРОННЫХ функций, который
        1) управляет выполнением асинхронного кода (asyncio.EventLoop) - когда задача ждет (например, await asyncio.sleep()), переключается на другую
        2) позволяет выполнять много задач параллельно в одном потоке
        
        !!! Синхронные функции блокируют Event Loop !!! Если запустить СИНХРОННУЮ задачу в Event Loop => Другие АСИНХРОННЫЕ задачи не выполняются.
        
        Executor — это пул потоков или процессов, который выполняет СИНХРОННЫЕ функции в отдельном потоке, не блокируя Event Loop.
        
        Args:
            task: Задача для выполнения
        Returns:
            Результат выполнения задачи или None в случае ошибки
        """
        # Формируем строку с идентификатором задачи
        task_id_str = f" (ID: {task.task_id})" if task.task_id else ""
        # Логирование начала выполнения задачи
        logger.info(f"Executing task{task_id_str}")
        
        try:
            # Проверяем, является ли функция корутиной
            if asyncio.iscoroutinefunction(task.func):
                # Если функция АСИНХРОННАЯ (корутина), выполняется напрямую с await - то есть работает через Event Loop
                result = await task.func(*task.args, **task.kwargs)
            else:
                # Если функиция СИНХРОННАЯ - нужно запускать через Executor, чтобы не блокировать Event Loop (иначе все остльные асинхронные задачи не выполняются)
                # сохраняем текущий event loop в переменную loop
                loop = asyncio.get_event_loop()
                # Запускаем синхронную функцию в отдельном потоке, не блокируя Event Loop.
                result = await loop.run_in_executor(None, lambda: task.func(*task.args, **task.kwargs))
            # Логирование успешного выполнения задачи
            logger.info(f"Task{task_id_str} completed successfully")
            # Возвращаем результат выполнения задачи
            return result
        # Обработка отмены задачи (KeyboardInterrupt, CancelledError)
        except (KeyboardInterrupt, asyncio.CancelledError) as e:
            # Логирование отмены задачи
            logger.warning(f"Task{task_id_str} was cancelled/interrupted: {e}")
            # Пробрасываем исключение дальше, чтобы worker мог обработать отмену корректно
            raise
        # Обработка ошибок
        except Exception as e:
            # Логирование ошибки выполнения задачи
            logger.error(f"Task{task_id_str} failed with error: {e}", exc_info=True)
            # Возвращаем None в случае ошибки
            return None
    

    async def _worker(self):
        """
        Воркер, который обрабатывает задачи из очереди последовательно.
        При ошибке в задаче не останавливается, продолжает обрабатывать следующие задачи.
        """
        # Логирование начала работы воркера
        logger.info("Task queue worker started")
        # Пока воркер запущен, обрабатываем задачи из очереди
        while self._worker_running:
            try:
                try:
                    # Получаем задачу из очереди с таймаутом для возможности проверки флага (если очередь пуста, то ждем 1 секунду)
                    task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Таймаут - проверяем, нужно ли продолжать работу
                    continue
                # Выполняем задачу
                await self._execute_task(task)
                # После выполнения задачи, помечаем задачу как выполненную
                # метод asyncio.Queue, который сообщает очереди, что задача завершена. 
                self._queue.task_done()
            except asyncio.CancelledError:
                # Если воркер был остановлен, то логируем это
                logger.info("Task queue worker cancelled")
                break
            except Exception as e:
                # Логируем ошибку
                logger.error(f"Unexpected error in worker: {e}", exc_info=True)
                # Продолжаем работу даже при неожиданной ошибке (чтобы не останавливать воркер)
                continue
        # Логирование остановки воркера
        logger.info("Task queue worker stopped")
    

    def start_worker(self):
        """
        Запустить воркер для обработки задач
        """
        if self._worker_running:
            logger.warning("Worker is already running")
            return
        
        self._worker_running = True
        # Оборачиваем корутину в объект asyncio.Task и планируем её выполнение в Event Loop. (то есть запускаем воркер)
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Task queue worker started")
    

    async def stop_worker(self, wait: bool = True):
        """
        Остановить воркер
        Args:
            wait: Если True, дождаться завершения текущей задачи и очистки очереди
        """
        if not self._worker_running:
            logger.warning("Worker is not running")
            return
        
        self._worker_running = False
        
        if wait:
            # Ждем завершения всех задач в очереди
            await self._queue.join()
        
        if self._worker_task:
            # Останавливаем воркер
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Task queue worker stopped")
    

    async def wait_empty(self):
        """Дождаться, пока очередь не станет пустой"""
        await self._queue.join()

'''
# Пример использования
async def example_task_1(name: str):
    """Пример асинхронной задачи"""
    print(f"Task 1 executing: {name}")
    await asyncio.sleep(1)
    return f"Task 1 completed: {name}"

def example_task_2(number: int):
    """Пример синхронной задачи"""
    print(f"Task 2 executing: {number}")
    return f"Task 2 completed: {number}"

async def main():
    """Пример использования очереди задач"""
    queue = TaskQueue(maxsize=200)
    
    # Запускаем воркер
    queue.start_worker()
    
    # Добавляем задачи
    await queue.put(example_task_1, "test1", task_id="task-1")
    await queue.put(example_task_2, 42, task_id="task-2")
    await queue.put(example_task_1, "test3", task_id="task-3")
    
    # Ждем завершения всех задач
    await queue.wait_empty()
    
    # Останавливаем воркер
    await queue.stop_worker()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

'''