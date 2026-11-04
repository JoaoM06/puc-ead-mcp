from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Course:
    id: int
    shortname: str
    fullname: str
    viewurl: str
    startdate: int = 0
    enddate: int = 0
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CourseModule:
    id: int
    name: str
    module: str
    modname: str
    url: str
    sectionid: int
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Section:
    id: int
    number: int
    title: str
    cmlist: list[int] = field(default_factory=list)
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CourseState:
    course_id: int
    sections: list[Section]
    modules: list[CourseModule]

    def section_of(self, cm_id: int) -> Section | None:
        for s in self.sections:
            if cm_id in s.cmlist:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "sections": [s.to_dict() for s in self.sections],
            "modules": [m.to_dict() for m in self.modules],
        }
