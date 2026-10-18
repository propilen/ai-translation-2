from pathlib import Path
import subprocess

class TikalError(RuntimeError):
    pass


class TikalCancelled(RuntimeError):
    pass


class TikalClient:
    def __init__(self, executable: Path, filter_config: Path | None = None) -> None:
        self.executable = executable
        self.filter_config = filter_config

    def _filter_arguments(self) -> list[str]:
        return ["-fc", str(self.filter_config)] if self.filter_config else []

    def _run(self, arguments: list[str], cancel_check=None) -> tuple[str, str]:
        if not self.executable.is_file():
            raise TikalError(f"Tikal не найден: {self.executable}")
        process = subprocess.Popen(
            [str(self.executable), *arguments],
            # tikal.exe loads its Java classpath from the current directory.
            # It must therefore be started from the Okapi installation folder,
            # not from the web server's working directory.
            cwd=self.executable.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            while True:
                if cancel_check and cancel_check():
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise TikalCancelled("Конвертация через Tikal отменена")
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except Exception:
            if process.poll() is None:
                process.kill()
                process.communicate()
            raise
        if process.returncode != 0:
            details = (stderr or stdout).strip()
            raise TikalError(f"Tikal завершился с кодом {process.returncode}: {details}")
        return stdout, stderr

    def extract(self, source_docx: Path, xliff_dir: Path, source_lang: str, target_lang: str, cancel_check=None) -> Path:
        self._run([
            "-x", "-seg", *self._filter_arguments(), "-sl", source_lang, "-tl", target_lang,
            "-od", str(xliff_dir), str(source_docx),
        ], cancel_check)
        output = xliff_dir / f"{source_docx.name}.xlf"
        if not output.is_file():
            raise TikalError(f"После извлечения не найден XLIFF: {output}")
        return output

    def merge(self, xliff_file: Path, source_dir: Path, output_dir: Path, source_lang: str, target_lang: str, cancel_check=None) -> Path:
        self._run([
            "-m", *self._filter_arguments(), "-sl", source_lang, "-tl", target_lang,
            "-sd", str(source_dir), "-od", str(output_dir), str(xliff_file),
        ], cancel_check)
        expected = output_dir / xliff_file.name.removesuffix(".xlf").replace(".docx", ".out.docx")
        if expected.is_file():
            return expected
        generated = list(output_dir.glob("*.docx"))
        if len(generated) == 1:
            return generated[0]
        raise TikalError("Tikal не создал итоговый DOCX в папке out")
